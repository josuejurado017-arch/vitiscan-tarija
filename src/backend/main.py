"""FastAPI del perfil demo binario; NO implementa el contrato HTTP JSON congelado."""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from src.backend.database import DEFAULT_DB_PATH, Database, IdentityConflict
from src.backend.idw_interpolation import LAYERS, generate_heatmap
from src.backend.seed_tarija import run_live_simulation
from src.simulator.binary_protocol import CONTRACT

FRONTEND_PATH = Path(__file__).resolve().parents[1] / 'frontend'
DEMO_COOKIE = 'vitiscan_local_demo'


@dataclass(frozen=True)
class Settings:
    ingest_token: str = field(default='', repr=False)
    operator_token: str = field(default='', repr=False)
    sim_actions_enabled: bool = False
    cors_origins: tuple[str, ...] = ()
    app_mode: str = 'simulation'
    dashboard_local_demo: bool = False

    @classmethod
    def from_env(cls):
        return cls(ingest_token=os.environ.get('GATEWAY_INGEST_TOKEN', ''),
                   operator_token=os.environ.get('OPERATOR_TOKEN', ''),
                   sim_actions_enabled=os.environ.get('SIM_ACTIONS_ENABLED', '').lower() == 'true',
                   cors_origins=tuple(origin.strip() for origin in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
                                      if origin.strip()),
                   app_mode=os.environ.get('APP_MODE', 'simulation'),
                   dashboard_local_demo=os.environ.get('DASHBOARD_LOCAL_DEMO', '').lower() == 'true')


class PacketMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gateway_id: Literal['GW-00'] = 'GW-00'
    mode: Literal['simulation'] = 'simulation'
    cycle_id: UUID
    received_at: AwareDatetime
    latency_ms: float | None = Field(default=None, ge=0, le=120000, strict=True, allow_inf_nan=False)


class HexPacket(PacketMetadata):
    payload_hex: str = Field(min_length=12, max_length=4096, strict=True)


class SimulationCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['cascade', 'failover', 'fire', 'restore']
    idempotency_key: UUID
    mode: Literal['simulation'] = 'simulation'


def authorize(request: Request, token: str) -> None:
    if not token:
        raise HTTPException(503, 'Token no configurado en el servidor.')
    supplied = request.headers.get('authorization', '')
    expected = 'Bearer ' + token
    if not hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
        raise HTTPException(401, 'Bearer invalido o ausente.', headers={'WWW-Authenticate': 'Bearer'})


async def limited_body(request: Request, maximum: int = 65536) -> bytes:
    if request.headers.get('content-encoding', 'identity') != 'identity':
        raise HTTPException(415, 'No se admite compresion entrante.')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(413, 'Cuerpo demasiado grande.')
        body.extend(chunk)
    return bytes(body)


def parse_model(model, body: bytes):
    try:
        document = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'JSON invalido.') from None
    try:
        return model.model_validate(document)
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json(include_input=False, include_context=False))) from None


def create_app(db_path: str | Path | None = None, *, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.app_mode != 'simulation':
        raise ValueError('Backend demo: APP_MODE debe ser simulation. No usar bases/credenciales reales.')
    if any('*' in origin for origin in settings.cors_origins):
        raise ValueError('CORS requiere origins explicitos, sin wildcard.')
    database = Database(db_path or os.environ.get('VITISCAN_DB_PATH', DEFAULT_DB_PATH))
    simulation_lock = threading.Lock()
    local_session = secrets.token_urlsafe(32)

    def is_local_dashboard(request: Request) -> bool:
        # Host + peer checks: no trust in X-Forwarded-For/Host for this capability.
        try:
            local_peer = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local_peer = False
        return bool(settings.dashboard_local_demo and local_peer
                    and request.url.hostname in ('127.0.0.1', 'localhost', '::1'))

    @asynccontextmanager
    async def lifespan(application):
        await run_in_threadpool(database.initialize)
        yield

    application = FastAPI(title='VitiScan Tarija - perfil demo binario', version='0.3.0',
                          description='Solo simulacion; extension HTTP no conforme al contrato JSON v2 congelado.',
                          lifespan=lifespan)
    application.state.database = database
    application.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
        allow_methods=['GET', 'POST'],
        allow_headers=['Authorization', 'Content-Type', 'X-Gateway-ID', 'X-Cycle-ID',
                       'X-Received-At', 'X-Latency-Ms'],
    )

    @application.exception_handler(sqlite3.Error)
    async def storage_error(request, exc):
        return JSONResponse(status_code=503, content={'detail': 'SQLite no disponible; transaccion no confirmada.'})

    @application.exception_handler(IdentityConflict)
    async def identity_error(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    @application.post('/api/v1/gateway/ingest')
    async def ingest(request: Request):
        authorize(request, settings.ingest_token)
        content_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
        if content_type not in ('application/json', 'application/octet-stream'):
            raise HTTPException(415, 'Usar application/octet-stream o application/json con payload_hex.')
        body = await limited_body(request, 246 if content_type == 'application/octet-stream' else 65536)
        if content_type == 'application/json':
            metadata = parse_model(HexPacket, body)
            try:
                payload = bytes.fromhex(metadata.payload_hex)
            except ValueError:
                raise HTTPException(422, 'payload_hex no es hexadecimal valido.') from None
        else:
            try:
                values = {'cycle_id': request.headers.get('x-cycle-id'),
                          'received_at': request.headers.get('x-received-at'),
                          'gateway_id': request.headers.get('x-gateway-id', 'GW-00')}
                if 'x-latency-ms' in request.headers:
                    values['latency_ms'] = float(request.headers['x-latency-ms'])
                metadata = PacketMetadata.model_validate(values)
            except (ValidationError, ValueError):
                raise HTTPException(422, 'Metadatos externos invalidos: X-Cycle-ID y X-Received-At obligatorios.') from None
            payload = body
        if len(payload) > 246:
            raise HTTPException(413, 'Una trama admite como maximo 246 bytes.')
        try:
            return await run_in_threadpool(
                database.ingest, payload, cycle_id=str(metadata.cycle_id),
                received_at=metadata.received_at, gateway_id=metadata.gateway_id,
                latency_ms=metadata.latency_ms,
                latency_source='gateway_external' if metadata.latency_ms is not None else None,
            )
        except IdentityConflict:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @application.get('/api/v1/nodes/status')
    @application.get('/api/v1/topology')
    def nodes_status(mode: Literal['simulation'] = 'simulation'):
        return {'mode': mode, 'nodes': database.node_status(),
                'metadata_source': 'coordinador externo; RSSI no existe en la trama binaria'}

    @application.get('/api/v1/heatmap/{layer}')
    def heatmap(layer: str, grid_m: int = Query(default=11), mode: Literal['simulation'] = 'simulation'):
        if layer not in LAYERS:
            raise HTTPException(404, 'Capa desconocida: ' + ', '.join(LAYERS))
        if grid_m not in (11, 22):
            raise HTTPException(422, 'grid_m debe ser 11 o 22.')
        return generate_heatmap(database.latest_readings(), layer, grid_m=grid_m)

    @application.get('/api/v1/alerts/fire')
    def fire_alerts(mode: Literal['simulation'] = 'simulation'):
        return {'mode': mode, 'alerts': database.alerts()}

    def trigger_sync(command: SimulationCommand):
        if not simulation_lock.acquire(blocking=False):
            raise HTTPException(409, 'Hay una simulacion activa en este proceso.')
        try:
            key = str(command.idempotency_key)
            cached = database.claim_run(key, command.action)
            if cached is not None:
                return cached
            result = run_live_simulation(database, command.action)
            database.finish_run(key, result)
            return result
        finally:
            simulation_lock.release()

    @application.post('/api/v1/sim/trigger')
    async def trigger(request: Request):
        if not settings.sim_actions_enabled:
            raise HTTPException(403, 'SIM_ACTIONS_ENABLED esta deshabilitado.')
        if request.headers.get('authorization'):
            authorize(request, settings.operator_token)
        elif is_local_dashboard(request):
            origin = request.headers.get('origin')
            if origin != str(request.base_url).rstrip('/'):
                raise HTTPException(403, 'La sesion demo requiere Origin del mismo servidor local.')
            cookie = request.cookies.get(DEMO_COOKIE, '')
            if not hmac.compare_digest(cookie.encode('utf-8'), local_session.encode('utf-8')):
                raise HTTPException(401, 'Abrir el dashboard local para iniciar la sesion demo.')
        else:
            authorize(request, settings.operator_token)
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Usar application/json.')
        command = parse_model(SimulationCommand, await limited_body(request))
        return await run_in_threadpool(trigger_sync, command)

    @application.get('/api/v1/dashboard/config')
    def dashboard_config(request: Request):
        return JSONResponse({
            'mode': 'simulation', 'gateway': CONTRACT['topology']['gateway'],
            'superframe_ms': 1500, 'listen_window_ms': 35, 'alert_poll_ms': 500,
            'actions_enabled': settings.sim_actions_enabled,
            'auth_mode': 'local_cookie' if is_local_dashboard(request) else 'bearer',
        }, headers={'Cache-Control': 'no-store'})

    @application.get('/', include_in_schema=False)
    def dashboard(request: Request):
        response = FileResponse(FRONTEND_PATH / 'index.html', headers={'Cache-Control': 'no-store'})
        if is_local_dashboard(request) and settings.sim_actions_enabled:
            response.set_cookie(DEMO_COOKIE, local_session, httponly=True, samesite='strict',
                                secure=request.url.scheme == 'https', path='/api/v1/sim')
        return response

    # Last: static files never mask /api/* routes, /docs or /openapi.json.
    application.mount('/', StaticFiles(directory=FRONTEND_PATH), name='frontend')

    return application


app = create_app()
