"""FastAPI del perfil demo binario; NO implementa el contrato HTTP JSON congelado."""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from src.backend.database import DEFAULT_DB_PATH, Database, IdentityConflict
from src.backend.idw_interpolation import LAYERS, generate_heatmap
from src.backend.seed_tarija import run_live_simulation


@dataclass(frozen=True)
class Settings:
    ingest_token: str = field(default='', repr=False)
    operator_token: str = field(default='', repr=False)
    sim_actions_enabled: bool = False
    cors_origins: tuple[str, ...] = ()
    app_mode: str = 'simulation'

    @classmethod
    def from_env(cls):
        return cls(ingest_token=os.environ.get('GATEWAY_INGEST_TOKEN', ''),
                   operator_token=os.environ.get('OPERATOR_TOKEN', ''),
                   sim_actions_enabled=os.environ.get('SIM_ACTIONS_ENABLED', '').lower() == 'true',
                   cors_origins=tuple(origin.strip() for origin in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
                                      if origin.strip()),
                   app_mode=os.environ.get('APP_MODE', 'simulation'))


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
    action: Literal['cascade', 'failover', 'fire']
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
        authorize(request, settings.operator_token)
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Usar application/json.')
        command = parse_model(SimulationCommand, await limited_body(request))
        return await run_in_threadpool(trigger_sync, command)

    return application


app = create_app()
