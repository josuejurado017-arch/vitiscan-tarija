"""Historia sintetica de Tarija y puente de tramas REALES del simulador al Gateway."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backend.database import DEFAULT_DB_PATH, Database, utc_now
from src.simulator.binary_protocol import (
    SYNTHETIC, MessageType, NodeReading, fragment_readings,
)
from src.simulator.cascade_network import CascadeNetwork


def seed_history(database: Database, *, periods: int = 96, now: datetime | None = None) -> dict:
    """24 h a 15 min por defecto; climatologia ILUSTRATIVA, no observaciones reales.

    Identidades y valores son deterministas por instante/nodo: repetir no duplica
    muestras ni sobrescribe trabajo previo. No borra ni reinicializa datos.
    """
    if isinstance(periods, bool) or not isinstance(periods, int) or not 1 <= periods <= 672:
        raise ValueError('periods debe estar entre 1 y 672 (una semana).')
    database.initialize()
    end = int((now or utc_now()).timestamp() // 900) * 900
    accepted = duplicates = 0
    for step in range(periods):
        timestamp = end - (periods - 1 - step) * 900
        received_at = datetime.fromtimestamp(timestamp, timezone.utc)
        local = received_at.astimezone(timezone(timedelta(hours=-4)))
        hour = local.hour + local.minute / 60
        sun = math.sin(2 * math.pi * (hour - 9) / 24)
        readings = []
        for node_id in range(1, 21):
            branch, level = (node_id - 1) % 5 + 1, (node_id - 1) // 5 + 1
            rng = random.Random(timestamp + node_id * 101)
            ambient = 23 + 9 * sun + 0.25 * branch + rng.uniform(-0.7, 0.7)
            soil = 21 + 4 * math.sin(2 * math.pi * (hour - 11) / 24) + level * 0.3
            moisture = 46 - level * 2.2 + branch * 1.2 - 3 * sun + rng.uniform(-1, 1)
            readings.append(NodeReading(
                node_id, round(soil * 10), round(moisture * 100), round(ambient * 10),
                round(57 - 17 * sun + rng.uniform(-2, 2)), round(65 + branch * 5 + rng.uniform(0, 20)),
                96 - level, SYNTHETIC,
            ))
        cycle_id = str(uuid5(NAMESPACE_URL, f'vitiscan:tarija:synthetic-history-v1:{timestamp}'))
        for packet in fragment_readings(readings, level=1, sender_id=1, parent_id=0):
            result = database.ingest(packet, cycle_id=cycle_id, received_at=received_at)
            accepted += len(result['accepted'])
            duplicates += len(result['duplicates'])
    return {'nodes': 20, 'periods': periods, 'accepted': accepted, 'duplicates': duplicates,
            'mode': 'simulation', 'history': 'sintetica, no meteorologia medida'}


def ingest_gateway_events(database: Database, network: CascadeNetwork, events: list,
                          *, cycle_id: str, alert_started_ms: int | None = None) -> list[dict]:
    """Ingiere solo bytes de RadioEvent que efectivamente recibio el nodo 0.

    UTC marca cada recepcion al reproducirla en el Gateway simulado. No se resta
    la duracion virtual del escenario al reloj de pared: eso podria hacer una
    alerta nueva mas antigua que la cascada anterior ejecutada sin esperar.
    Latencia/fase RF conservan el reloj virtual externo. Deduplica replicas sin
    fabricar una trama agregada del resultado.
    """
    seen, results = set(), []
    for event in events:
        if 0 not in event.received_by or event.kind not in (MessageType.CASCADE_DATA, MessageType.FIRE_ALERT):
            continue
        identity = (event.kind, event.payload[6:])
        if identity in seen:
            continue
        seen.add(identity)
        metadata = {}
        if event.kind == MessageType.FIRE_ALERT:
            window = next(window for window in network.listen_windows if window.node_id == 0
                          and window.start_ms <= event.start_ms and event.end_ms <= window.end_ms)
            if alert_started_ms is None:
                raise ValueError('Falta instante externo de inyeccion de alerta.')
            metadata = {'latency_ms': event.end_ms - alert_started_ms,
                        'latency_source': 'simulator_external',
                        'listen_window_ms': window.end_ms - window.start_ms,
                        'gateway_phase_ms': event.end_ms % network.timing['superframe']}
        result = database.ingest(
            event.payload, cycle_id=cycle_id,
            received_at=utc_now(),
            **metadata,
        )
        results.append({**result, 'payload_hex': event.payload.hex(' '),
                        'msg_type': int(event.kind), **metadata})
    return results


def run_live_simulation(database: Database, action: str = 'cascade') -> dict:
    """Escenarios independientes: no acumulan nodos caidos entre llamadas."""
    if action not in ('cascade', 'failover', 'fire', 'restore'):
        raise ValueError('Accion debe ser cascade, failover, fire o restore.')
    database.initialize()
    network = CascadeNetwork()
    network.discover()
    stages, packets, failovers = [], [], []

    def cascade_stage():
        result = network.run_cascade()
        stage_packets = ingest_gateway_events(database, network, network._last_cascade_events,
                                              cycle_id=str(uuid4()))
        database.update_network_state(network)
        packets.extend(stage_packets)
        failovers.extend({'node_id': node_id, 'old_parent': old, 'new_parent': new}
                         for node_id, old, new in result.failovers)
        stages.append({'epoch': result.epoch, 'reading_count': len(result.readings),
                       'missing_node_ids': result.missing_node_ids,
                       'overflow_node_ids': result.overflow_node_ids})
        return result

    latency = None
    if action == 'fire':
        fire = network.trigger_fire(16, gas_smoke_ppm=450)
        started = network.clock_ms
        offset = len(network.events)
        alerts = network.run_fire_alerts(4)
        if fire.pack() not in alerts:
            raise RuntimeError('La alerta V-16 no llego al Gateway.')
        latency = alerts[fire.pack()] - started
        packets = ingest_gateway_events(database, network, network.events[offset:],
                                         cycle_id=str(uuid4()), alert_started_ms=started)
        database.update_network_state(network)
        reading_count, missing = 1, []
    else:
        result = cascade_stage()
        if action == 'failover':
            network.set_node_alive(1, False)
            cascade_stage()
            result = cascade_stage()
        reading_count, missing = len(result.readings), result.missing_node_ids
    closed_demo_alerts = 0
    if action == 'restore':
        # Solo esta base sintetica. Conservar historial; no afirmar extincion real.
        with database.connection(write=True) as connection:
            closed_demo_alerts = connection.execute(
                "UPDATE fire_alerts SET state='inactive' WHERE state='active'"
            ).rowcount
    network.validate_trace()
    return {'run_id': str(uuid4()), 'mode': 'simulation', 'action': action,
            'status': 'partial' if missing else 'completed', 'reading_count': reading_count,
            'missing_node_ids': missing, 'failovers': failovers, 'stages': stages,
            'packets': packets, 'latency_ms': latency, 'listen_window_ms': 35,
            'superframe_ms': 1500, 'trace_validated': True, 'closed_demo_alerts': closed_demo_alerts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument('--periods', type=int, default=96)
    parser.add_argument('--live', choices=('cascade', 'failover', 'fire'), default='cascade')
    args = parser.parse_args()
    database = Database(args.db)
    history = seed_history(database, periods=args.periods)
    live = run_live_simulation(database, args.live)
    print(f'SQLite WAL: {database.path}')
    print(json.dumps(history, ensure_ascii=False))
    print(f'Puente binario en vivo: {live["action"]}; {live["reading_count"]}/20 lecturas; '
          f'{len(live["packets"])} tramas recibidas en Gateway.')
    if live['packets']:
        print('HEX real: ' + live['packets'][0]['payload_hex'])
    print('SEED OK. Datos sinteticos; sin radio real ni calibracion MQ-2.')


if __name__ == '__main__':
    main()
