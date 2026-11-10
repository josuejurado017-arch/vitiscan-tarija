"""Persistencia SQLite del perfil demo. Tiempos/epochs son metadatos externos."""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import astuple
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.simulator.binary_protocol import (
    CONTRACT, GAS_INVALID, SYNTHETIC, MessageType, ProtocolError, unpack_packet,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / 'data' / 'vitiscan_tarija.db'
GAS_THRESHOLD = CONTRACT['fire_alerts']['thresholds_frozen']['gas_ppm_gte']


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timestamp debe incluir zona horaria UTC/RFC3339.')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class IdentityConflict(ValueError):
    """La misma identidad externa no puede cambiar contenido."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id INTEGER PRIMARY KEY CHECK(node_id BETWEEN 1 AND 20),
    label TEXT NOT NULL UNIQUE,
    branch INTEGER NOT NULL CHECK(branch BETWEEN 1 AND 5),
    level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 4),
    east_m REAL NOT NULL, north_m REAL NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL,
    primary_parent INTEGER NOT NULL,
    backup_parent INTEGER,
    operational_parent_id INTEGER,
    operational_backup_id INTEGER,
    rssi_dbm REAL,
    state TEXT NOT NULL DEFAULT 'seed',
    state_received_at REAL
);
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY,
    gateway_id TEXT NOT NULL CHECK(gateway_id = 'GW-00'),
    cycle_id TEXT NOT NULL,
    node_id INTEGER NOT NULL REFERENCES nodes(node_id),
    soil_temp_x10 INTEGER NOT NULL CHECK(soil_temp_x10 BETWEEN -550 AND 1250),
    soil_moisture INTEGER NOT NULL CHECK(soil_moisture BETWEEN 0 AND 10000),
    amb_temp_x10 INTEGER NOT NULL CHECK(amb_temp_x10 BETWEEN -400 AND 800),
    amb_humidity INTEGER NOT NULL CHECK(amb_humidity BETWEEN 0 AND 100),
    gas_smoke_ppm INTEGER NOT NULL CHECK(gas_smoke_ppm BETWEEN 0 AND 1000),
    battery_pct INTEGER NOT NULL CHECK(battery_pct BETWEEN 0 AND 100),
    status_flags INTEGER NOT NULL CHECK(status_flags BETWEEN 0 AND 255),
    received_at TEXT NOT NULL,
    received_unix REAL NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('telemetry', 'alert')),
    raw_reading BLOB NOT NULL CHECK(length(raw_reading) = 12),
    identity_metadata TEXT NOT NULL,
    UNIQUE(gateway_id, cycle_id, node_id)
);
CREATE INDEX IF NOT EXISTS telemetry_latest
    ON telemetry(gateway_id, node_id, received_unix DESC, id DESC);
CREATE TABLE IF NOT EXISTS fire_alerts (
    id INTEGER PRIMARY KEY,
    telemetry_id INTEGER NOT NULL REFERENCES telemetry(id),
    node_id INTEGER NOT NULL REFERENCES nodes(node_id),
    raw_reading BLOB NOT NULL CHECK(length(raw_reading) = 12),
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    first_seen_unix REAL NOT NULL, last_seen_unix REAL NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active', 'inactive')),
    reason TEXT NOT NULL CHECK(reason IN ('radio_flag', 'gas')),
    critical INTEGER NOT NULL DEFAULT 1 CHECK(critical = 1),
    latency_ms REAL CHECK(latency_ms >= 0),
    latency_source TEXT,
    listen_window_ms INTEGER CHECK(listen_window_ms = 35),
    gateway_phase_ms INTEGER CHECK(gateway_phase_ms BETWEEN 0 AND 1499)
);
CREATE INDEX IF NOT EXISTS fire_alerts_recent ON fire_alerts(state, last_seen_unix DESC);
CREATE INDEX IF NOT EXISTS fire_alerts_origin ON fire_alerts(node_id, last_seen_unix DESC);
CREATE TABLE IF NOT EXISTS simulation_runs (
    idempotency_key TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    response_json TEXT
);
"""


class Database:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path).resolve()

    @contextmanager
    def connection(self, *, write: bool = False):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=10000')
            connection.execute('PRAGMA synchronous=FULL')
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]
            if mode.lower() != 'wal':
                raise RuntimeError('SQLite no pudo activar WAL.')
            connection.executescript(SCHEMA)
            connection.executemany(
                '''INSERT INTO nodes(node_id,label,branch,level,east_m,north_m,lat,lon,
                       primary_parent,backup_parent) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(node_id) DO NOTHING''',
                [(row['node_id'], row['label'], row['branch'], row['level'], row['east_m'],
                  row['north_m'], row['lat'], row['lon'], row['parent_id'], row['backup_parent_id'])
                 for row in CONTRACT['topology']['nodes']],
            )

    def ingest(self, payload: bytes, *, cycle_id: str, received_at: datetime,
               gateway_id: str = 'GW-00', latency_ms: float | None = None,
               latency_source: str | None = None, listen_window_ms: int | None = None,
               gateway_phase_ms: int | None = None) -> dict:
        """Una trama validada, una transaccion. Sin reloj/latencia inferidos de radio.

        Duplicados se reconocen por identidad externa y los 12 bytes originales,
        independientemente de la cabecera del repetidor. Conflictos hacen rollback.
        """
        header, readings = unpack_packet(payload)
        if header.msg_type not in (MessageType.CASCADE_DATA, MessageType.FIRE_ALERT):
            raise ProtocolError('Solo DATA y FIRE_ALERT se ingieren como lecturas.')
        if header.msg_type == MessageType.CASCADE_DATA and header.parent_id != 0:
            raise ProtocolError('La trama DATA no esta dirigida al Gateway.')
        if gateway_id != 'GW-00':
            raise ValueError('Gateway fuera de allowlist.')
        cycle_id = str(UUID(str(cycle_id)))
        received_text = utc_text(received_at)
        received_unix = received_at.timestamp()
        if received_unix > utc_now().timestamp() + 5:
            raise ValueError('Timestamp de recepcion mas de 5 s en el futuro.')
        if any(not reading.status_flags & SYNTHETIC for reading in readings):
            raise ValueError('Esta base admite exclusivamente mode=simulation.')
        if latency_ms is not None:
            if (isinstance(latency_ms, bool) or not isinstance(latency_ms, (int, float))
                    or not math.isfinite(latency_ms) or not 0 <= latency_ms <= 120000):
                raise ValueError('Latencia externa invalida.')
            if latency_source not in ('simulator_external', 'gateway_external'):
                raise ValueError('Indicar fuente externa de latencia.')
            latency_ms = float(latency_ms)
        elif latency_source is not None:
            raise ValueError('Fuente de latencia sin latencia.')
        if listen_window_ms is not None and (isinstance(listen_window_ms, bool) or listen_window_ms != 35):
            raise ValueError('La ventana de escucha debe ser 35 ms.')
        if gateway_phase_ms is not None and (
                isinstance(gateway_phase_ms, bool) or not isinstance(gateway_phase_ms, int)
                or not 1200 <= gateway_phase_ms < 1420):
            raise ValueError('Fase de recepcion de alerta fuera de reserva.')
        kind = 'alert' if header.msg_type == MessageType.FIRE_ALERT else 'telemetry'
        metadata = json.dumps([kind, received_text, latency_ms, latency_source,
                               listen_window_ms, gateway_phase_ms], separators=(',', ':'))
        accepted, duplicates = [], []
        critical = False
        with self.connection(write=True) as connection:
            connection.execute("UPDATE fire_alerts SET state='inactive' WHERE last_seen_unix < ?",
                               (utc_now().timestamp() - 120,))
            for reading in readings:
                raw = reading.pack()
                previous = connection.execute(
                    'SELECT raw_reading,identity_metadata FROM telemetry '
                    'WHERE gateway_id=? AND cycle_id=? AND node_id=?',
                    (gateway_id, cycle_id, reading.node_id),
                ).fetchone()
                is_critical = (header.msg_type == MessageType.FIRE_ALERT
                               or (not reading.status_flags & GAS_INVALID
                                   and reading.gas_smoke_ppm >= GAS_THRESHOLD))
                critical |= is_critical
                if previous is not None:
                    if previous['raw_reading'] != raw or previous['identity_metadata'] != metadata:
                        raise IdentityConflict(f'IDENTITY_CONFLICT: nodo {reading.node_id}')
                    duplicates.append(reading.node_id)
                    continue
                cursor = connection.execute(
                    '''INSERT INTO telemetry(gateway_id,cycle_id,node_id,soil_temp_x10,soil_moisture,
                           amb_temp_x10,amb_humidity,gas_smoke_ppm,battery_pct,status_flags,
                           received_at,received_unix,kind,raw_reading,identity_metadata)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (gateway_id, cycle_id, *astuple(reading), received_text, received_unix, kind, raw, metadata),
                )
                accepted.append(reading.node_id)
                if not is_critical:
                    continue
                recent = connection.execute(
                    '''SELECT id FROM fire_alerts WHERE node_id=? AND raw_reading=?
                       AND last_seen_unix BETWEEN ? AND ? ORDER BY last_seen_unix DESC LIMIT 1''',
                    (reading.node_id, raw, received_unix - 120, received_unix),
                ).fetchone()
                state = 'active' if received_unix >= utc_now().timestamp() - 120 else 'inactive'
                if recent:
                    connection.execute(
                        'UPDATE fire_alerts SET last_seen_at=?,last_seen_unix=?,state=? WHERE id=?',
                        (received_text, received_unix, state, recent['id']),
                    )
                else:
                    connection.execute(
                        '''INSERT INTO fire_alerts(telemetry_id,node_id,raw_reading,first_seen_at,
                               last_seen_at,first_seen_unix,last_seen_unix,state,reason,
                               latency_ms,latency_source,listen_window_ms,gateway_phase_ms)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (cursor.lastrowid, reading.node_id, raw, received_text, received_text,
                         received_unix, received_unix, state,
                         'radio_flag' if kind == 'alert' else 'gas', latency_ms, latency_source,
                         listen_window_ms, gateway_phase_ms),
                    )
        return {'gateway_id': gateway_id, 'cycle_id': cycle_id, 'accepted': accepted,
                'duplicates': duplicates, 'critical': critical, 'packet_bytes': len(payload)}

    def latest_readings(self, *, now: datetime | None = None) -> list[dict]:
        # Elegir ultima muestra ANTES de filtrar flags/edad: nunca backfill de canal invalido.
        cutoff = (now or utc_now()).timestamp() + 5
        with self.connection() as connection:
            rows = connection.execute(
                '''WITH ranked AS (
                     SELECT t.*, ROW_NUMBER() OVER (
                       PARTITION BY node_id ORDER BY received_unix DESC,id DESC) AS rank
                     FROM telemetry t WHERE gateway_id='GW-00' AND received_unix<=?
                   ) SELECT n.*,r.id AS telemetry_id,r.soil_temp_x10,r.soil_moisture,
                       r.amb_temp_x10,r.amb_humidity,r.gas_smoke_ppm,r.battery_pct,r.status_flags,
                       r.received_at,r.received_unix
                     FROM nodes n LEFT JOIN ranked r ON r.node_id=n.node_id AND r.rank=1
                     ORDER BY n.node_id''', (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def node_status(self) -> list[dict]:
        now = utc_now().timestamp()
        result = self.latest_readings()
        for row in result:
            if row['status_flags'] is not None and row['status_flags'] & (1 << 5):
                row['battery_pct'] = None
            if row['state'] == 'seed' and row['received_at']:
                row['state'] = 'online'
            if row['received_unix'] is not None and now - row['received_unix'] > 3600:
                row['state'] = 'stale'
            row['last_seen_at'] = row.pop('received_at')
            row['failover'] = (row['operational_parent_id'] is not None
                               and row['operational_parent_id'] != row['primary_parent'])
            row['using_backup_parent'] = (row['operational_parent_id'] is not None
                                          and row['operational_parent_id'] == row['backup_parent'])
            for name in ('rank', 'id', 'telemetry_id', 'received_unix', 'raw_reading'):
                row.pop(name, None)
        return result

    def update_network_state(self, network, *, received_at: datetime | None = None) -> None:
        """Solo coordinador externo: estos datos NO se extraen de la cabecera."""
        timestamp = (received_at or utc_now()).timestamp()
        rows = []
        for node in network.nodes.values():
            if not node.node_id:
                continue
            parent = node.primary_parent if node.alive else None
            state = 'offline' if not node.alive else 'orphan' if parent is None else 'online'
            rows.append((parent, node.backup_parent, network.rssi(node.node_id, parent)
                         if parent is not None else None, state, timestamp, node.node_id, timestamp))
        with self.connection(write=True) as connection:
            connection.executemany(
                '''UPDATE nodes SET operational_parent_id=?,operational_backup_id=?,rssi_dbm=?,
                     state=?,state_received_at=? WHERE node_id=?
                     AND (state_received_at IS NULL OR state_received_at<=?)''', rows,
            )

    def alerts(self) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                '''SELECT id,node_id,first_seen_at,last_seen_at,
                     CASE WHEN last_seen_unix < ? THEN 'inactive' ELSE state END AS state,
                     reason,critical,latency_ms,latency_source,listen_window_ms,gateway_phase_ms
                   FROM fire_alerts ORDER BY (last_seen_unix >= ?) DESC,last_seen_unix DESC,id
                   LIMIT 100''', (utc_now().timestamp() - 120,) * 2,
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_run(self, key: str, action: str) -> dict | None:
        with self.connection(write=True) as connection:
            row = connection.execute('SELECT * FROM simulation_runs WHERE idempotency_key=?', (key,)).fetchone()
            if row:
                if row['action'] != action:
                    raise IdentityConflict('Clave de simulacion reutilizada para otra accion.')
                if row['response_json'] is None:
                    raise IdentityConflict('Simulacion en curso o interrumpida; usar otra clave.')
                return json.loads(row['response_json'])
            connection.execute('INSERT INTO simulation_runs VALUES(?,?,NULL)', (key, action))
        return None

    def finish_run(self, key: str, result: dict) -> None:
        with self.connection(write=True) as connection:
            connection.execute('UPDATE simulation_runs SET response_json=? WHERE idempotency_key=?',
                               (json.dumps(result, separators=(',', ':')), key))
