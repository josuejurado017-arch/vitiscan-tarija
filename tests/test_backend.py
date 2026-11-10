r"""Ejecutar: .\venv\Scripts\python.exe -m unittest discover -s tests -v."""

import math
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from src.backend.database import ROOT, utc_now, utc_text
from src.backend.idw_interpolation import generate_heatmap, idw_value, to_local, to_wgs84
from src.backend.main import Settings, create_app
from src.backend.seed_tarija import seed_history
from src.simulator.binary_protocol import (
    CONTRACT, FIRE_TRIGGERED, GAS_INVALID, SYNTHETIC, Header, MessageType,
    NodeReading, pack_packet, unpack_packet,
)
from src.simulator.cascade_network import CascadeNetwork


class BackendTests(unittest.TestCase):
    def setUp(self):
        approved = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' / 'opencode'
        temporary = tempfile.TemporaryDirectory(prefix='vitiscan-backend-',
                                                dir=approved if approved.is_dir() else None)
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'test.db'
        self.settings = Settings(ingest_token='test-ingest', operator_token='test-operator',
                                 sim_actions_enabled=True, cors_origins=('http://localhost:5173',))
        self.app = create_app(self.path, settings=self.settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.database = self.app.state.database
        self.received_at = utc_now() - timedelta(seconds=2)
        self.sample = NodeReading(**CONTRACT['samples']['raw'])

    def packet(self, readings=None):
        readings = readings if readings is not None else [self.sample]
        return pack_packet(Header(MessageType.CASCADE_DATA, 1, 1, 0, len(readings)), readings)

    def ingest(self, payload=None, *, cycle_id=None, received_at=None):
        return self.client.post('/api/v1/gateway/ingest', content=payload if payload is not None else self.packet(),
                                headers={'Content-Type': 'application/octet-stream',
                                         'Authorization': 'Bearer test-ingest',
                                         'X-Cycle-ID': str(cycle_id or uuid4()),
                                         'X-Received-At': utc_text(received_at or self.received_at)})

    def trigger(self, action, key=None):
        return self.client.post('/api/v1/sim/trigger', headers={'Authorization': 'Bearer test-operator'},
                                json={'action': action, 'idempotency_key': str(key or uuid4())})

    def count(self, table):
        if table not in ('telemetry', 'fire_alerts', 'nodes'):
            raise ValueError(table)
        with self.database.connection() as connection:
            return connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_wal_and_twenty_nodes_geometry(self):
        with self.database.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        nodes = self.client.get('/api/v1/nodes/status').json()['nodes']
        self.assertEqual([node['label'] for node in nodes], [f'V-{i:02d}' for i in range(1, 21)])
        for node in nodes:
            self.assertIsNone(node['rssi_dbm'])
            self.assertIsNone(node['operational_parent_id'])
            self.assertIsNone(node['battery_pct'])
            previous = nodes[node['node_id'] - 6] if node['level'] > 1 else {'east_m': 0, 'north_m': 0}
            self.assertAlmostEqual(math.hypot(node['east_m'] - previous['east_m'],
                                             node['north_m'] - previous['north_m']), 22, places=3)

    def test_ingest_real_246_byte_packet(self):
        readings = [CascadeNetwork().sample(node_id) for node_id in range(1, 21)]
        payload = self.packet(readings)
        self.assertEqual(len(payload), 246)
        response = self.ingest(payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['accepted'], list(range(1, 21)))
        self.assertEqual(self.count('telemetry'), 20)
        with self.database.connection() as connection:
            rows = connection.execute('SELECT * FROM telemetry ORDER BY node_id').fetchall()
        for row, reading in zip(rows, readings):
            self.assertEqual(row['raw_reading'], reading.pack())
            self.assertEqual(row['received_at'], utc_text(self.received_at))

    def test_hex_and_raw_share_idempotency(self):
        cycle_id = str(uuid4())
        first = self.ingest(cycle_id=cycle_id)
        second = self.client.post('/api/v1/gateway/ingest', headers={'Authorization': 'Bearer test-ingest'},
                                  json={'payload_hex': self.packet().hex(' '), 'cycle_id': cycle_id,
                                        'received_at': utc_text(self.received_at)})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()['duplicates'], [1])
        self.assertEqual(self.count('telemetry'), 1)

    def test_corrupt_frames_are_rejected_without_writes(self):
        payload = self.packet()
        duplicate = Header(MessageType.CASCADE_DATA, 1, 1, 0, 2).pack() + self.sample.pack() * 2
        corrupt = [b'', payload[:5], payload[:-1], payload + b'\x00', b'\x00' + payload[1:],
                   payload[:1] + b'\x04' + payload[2:], payload[:5] + b'\x15' + payload[6:],
                   payload[:2] + b'\x04' + payload[3:], duplicate]
        for bad in corrupt:
            with self.subTest(payload=bad.hex()):
                response = self.ingest(bad)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.count('telemetry'), 0)

    def test_identity_conflict_rolls_back_packet_and_alert(self):
        cycle_id = uuid4()
        second = replace(self.sample, node_id=2)
        self.assertEqual(self.ingest(self.packet([second]), cycle_id=cycle_id).status_code, 200)
        payload = self.packet([replace(self.sample, gas_smoke_ppm=450),
                               replace(second, soil_temp_x10=216)])
        response = self.ingest(payload, cycle_id=cycle_id)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count('telemetry'), 1)
        self.assertEqual(self.count('fire_alerts'), 0)

    def test_flood_relay_headers_preserve_one_event(self):
        cycle_id = uuid4()
        reading = replace(self.sample, node_id=16, status_flags=SYNTHETIC | FIRE_TRIGGERED)
        for sender, level in ((16, 4), (11, 3)):
            payload = pack_packet(Header(MessageType.FIRE_ALERT, level, sender, 255, 1), [reading])
            response = self.ingest(payload, cycle_id=cycle_id)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['critical'])
        self.assertEqual(self.count('telemetry'), 1)
        self.assertEqual(self.count('fire_alerts'), 1)
        alert = self.database.alerts()[0]
        self.assertEqual(alert['reason'], 'radio_flag')
        self.assertIsNone(alert['latency_ms'])
        self.assertIsNone(alert['listen_window_ms'])

    def test_gas_threshold_and_demo_1000(self):
        for gas, critical in ((299, False), (300, True), (1000, True)):
            response = self.ingest(self.packet([replace(self.sample, gas_smoke_ppm=gas)]))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['critical'], critical)
        self.assertEqual(self.count('fire_alerts'), 2)

    def test_invalid_gas_does_not_trigger_and_invalid_battery_is_null(self):
        reading = replace(self.sample, gas_smoke_ppm=0, battery_pct=0,
                          status_flags=SYNTHETIC | GAS_INVALID | (1 << 5))
        response = self.ingest(self.packet([reading]))
        self.assertFalse(response.json()['critical'])
        self.assertEqual(self.count('fire_alerts'), 0)
        node = self.client.get('/api/v1/nodes/status').json()['nodes'][0]
        self.assertIsNone(node['battery_pct'])

    def test_external_latency_is_recorded_not_inferred(self):
        reading = replace(self.sample, gas_smoke_ppm=450, status_flags=SYNTHETIC | FIRE_TRIGGERED)
        payload = pack_packet(Header(MessageType.FIRE_ALERT, 1, 1, 255, 1), [reading])
        response = self.client.post('/api/v1/gateway/ingest', headers={'Authorization': 'Bearer test-ingest'},
                                    json={'payload_hex': payload.hex(), 'cycle_id': str(uuid4()),
                                          'received_at': utc_text(self.received_at), 'latency_ms': 1401})
        self.assertEqual(response.status_code, 200, response.text)
        alert = self.database.alerts()[0]
        self.assertEqual(alert['latency_ms'], 1401)
        self.assertEqual(alert['latency_source'], 'gateway_external')
        self.assertIsNone(alert['listen_window_ms'])

    def test_old_alert_is_inactive_not_extinguished(self):
        reading = replace(self.sample, gas_smoke_ppm=450)
        self.ingest(self.packet([reading]), received_at=utc_now() - timedelta(seconds=121))
        self.assertEqual(self.database.alerts()[0]['state'], 'inactive')

    def test_real_mode_and_uncalibrated_real_gas_rejected(self):
        reading = replace(self.sample, gas_smoke_ppm=0, status_flags=GAS_INVALID)
        self.assertEqual(self.ingest(self.packet([reading])).status_code, 422)
        self.assertEqual(self.client.get('/api/v1/nodes/status?mode=real').status_code, 422)
        with self.assertRaises(ValueError):
            create_app(self.path, settings=replace(self.settings, app_mode='real'))
        self.assertEqual(self.count('telemetry'), 0)

    def test_control_frames_and_wrong_gateway_destination_rejected(self):
        for payload in (pack_packet(Header(MessageType.BEACON, 0, 0, 255, 0)),
                        pack_packet(Header(MessageType.ACK, 0, 0, 1, 0)),
                        pack_packet(Header(MessageType.CASCADE_DATA, 2, 6, 1, 1), [self.sample])):
            self.assertEqual(self.ingest(payload).status_code, 422)
        self.assertEqual(self.count('telemetry'), 0)

    def test_heatmap_leaflet_grid_layers_and_normalization(self):
        readings = [CascadeNetwork().sample(node_id) for node_id in range(1, 21)]
        self.ingest(self.packet(readings))
        for layer in ('soil_moisture', 'soil_temp', 'amb_temp', 'gas_smoke_ppm', 'thermal_risk'):
            response = self.client.get('/api/v1/heatmap/' + layer)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result['source_count'], 20)
            self.assertEqual(len(result['points']), 289)
            self.assertEqual(len(result['values']), 289)
            self.assertTrue(all(-22 < lat < -21 and -65 < lon < -64 and 0 <= intensity <= 1
                                for lat, lon, intensity in result['points']))
        self.assertEqual(len(self.client.get('/api/v1/heatmap/soil_temp?grid_m=22').json()['points']), 81)
        self.assertEqual(self.client.get('/api/v1/heatmap/unknown').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/heatmap/soil_temp?grid_m=1').status_code, 422)

    def test_empty_heatmap(self):
        result = self.client.get('/api/v1/heatmap/soil_temp').json()
        self.assertEqual(result['source_count'], 0)
        self.assertEqual(result['points'], [])

    def test_latest_invalid_channel_is_not_backfilled(self):
        self.ingest(received_at=self.received_at - timedelta(seconds=10))
        invalid = replace(self.sample, soil_moisture=0, status_flags=SYNTHETIC | (1 << 1))
        self.ingest(self.packet([invalid]))
        self.assertEqual(self.client.get('/api/v1/heatmap/soil_moisture').json()['source_count'], 0)
        self.assertEqual(self.client.get('/api/v1/heatmap/soil_temp').json()['source_count'], 1)

    def test_stale_samples_and_future_reception(self):
        self.ingest(received_at=utc_now() - timedelta(seconds=3601))
        self.assertEqual(self.client.get('/api/v1/heatmap/soil_temp').json()['points'], [])
        self.assertEqual(self.client.get('/api/v1/nodes/status').json()['nodes'][0]['state'], 'stale')
        self.assertEqual(self.ingest(received_at=utc_now() + timedelta(seconds=60)).status_code, 422)

    def test_live_cascade_uses_actual_gateway_packets(self):
        response = self.trigger('cascade')
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['reading_count'], 20)
        self.assertEqual(len(result['packets']), 5)
        for packet in result['packets']:
            payload = bytes.fromhex(packet['payload_hex'])
            header, readings = unpack_packet(payload)
            self.assertEqual(header.parent_id, 0)
            with self.database.connection() as connection:
                rows = connection.execute('SELECT node_id,raw_reading FROM telemetry WHERE cycle_id=? ORDER BY node_id',
                                          (packet['cycle_id'],)).fetchall()
            stored = {row['node_id']: row['raw_reading'] for row in rows}
            self.assertEqual([stored[reading.node_id] for reading in readings],
                             [reading.pack() for reading in readings])

    def test_live_failover_v01_reports_active_backup(self):
        response = self.trigger('failover')
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual([stage['reading_count'] for stage in result['stages']], [20, 16, 19])
        self.assertEqual(result['missing_node_ids'], [1])
        self.assertIn({'node_id': 6, 'old_parent': 1, 'new_parent': 2}, result['failovers'])
        nodes = self.client.get('/api/v1/nodes/status').json()['nodes']
        self.assertEqual(nodes[0]['state'], 'offline')
        self.assertEqual(nodes[5]['operational_parent_id'], 2)
        self.assertTrue(nodes[5]['using_backup_parent'])
        self.assertTrue(nodes[5]['failover'])
        self.assertIsNotNone(nodes[5]['rssi_dbm'])
        self.assertEqual(self.count('telemetry'), 55)

    def test_live_fire_ff_latency_and_35ms_windows(self):
        response = self.trigger('fire')
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result['trace_validated'])
        self.assertEqual(result['listen_window_ms'], 35)
        self.assertEqual(result['reading_count'], 1)
        payload = bytes.fromhex(result['packets'][0]['payload_hex'])
        self.assertEqual(len(payload), 18)
        self.assertEqual(payload[1], 0xFF)
        self.assertEqual(unpack_packet(payload)[1][0].node_id, 16)
        alert = self.client.get('/api/v1/alerts/fire').json()['alerts'][0]
        self.assertEqual(alert['node_id'], 16)
        self.assertEqual(alert['latency_ms'], result['latency_ms'])
        self.assertLessEqual(alert['latency_ms'], 1500)
        self.assertEqual(alert['listen_window_ms'], 35)
        self.assertEqual(alert['latency_source'], 'simulator_external')
        self.assertTrue(1370 <= alert['gateway_phase_ms'] <= 1405)
        self.assertEqual(self.count('fire_alerts'), 1)

    def test_action_idempotency_and_conflicting_key(self):
        key = uuid4()
        first = self.trigger('fire', key)
        second = self.trigger('fire', key)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(self.count('telemetry'), 1)
        self.assertEqual(self.trigger('cascade', key).status_code, 409)

    def test_authentication_and_actions_disabled_by_default(self):
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', content=self.packet()).status_code, 401)
        response = self.client.post('/api/v1/sim/trigger', headers={'Authorization': 'Bearer test-ingest'},
                                    json={'action': 'fire', 'idempotency_key': str(uuid4())})
        self.assertEqual(response.status_code, 401)
        disabled = create_app(self.path, settings=Settings())
        with TestClient(disabled) as client:
            self.assertEqual(client.post('/api/v1/sim/trigger', json={}).status_code, 403)
            self.assertEqual(client.post('/api/v1/gateway/ingest', content=self.packet()).status_code, 503)

    def test_malformed_http_size_limits_and_metadata(self):
        auth = {'Authorization': 'Bearer test-ingest', 'Content-Type': 'application/json'}
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', content=b'{', headers=auth).status_code, 400)
        document = {'payload_hex': 'zz' * 18, 'cycle_id': str(uuid4()),
                    'received_at': utc_text(self.received_at)}
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', json=document, headers=auth).status_code, 422)
        document['payload_hex'] = self.packet().hex()
        document['extra'] = 'not allowed'
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', json=document, headers=auth).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', content=b'x' * 65537, headers=auth).status_code, 413)
        self.assertEqual(self.ingest(b'x' * 247).status_code, 413)
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', content=b'x',
                                         headers={'Authorization': 'Bearer test-ingest'}).status_code, 415)
        self.assertEqual(self.client.post('/api/v1/gateway/ingest', content=self.packet(),
                                         headers={'Authorization': 'Bearer test-ingest',
                                                  'Content-Type': 'application/octet-stream'}).status_code, 422)
        self.assertEqual(self.count('telemetry'), 0)

    def test_cors_explicit_allowlist(self):
        headers = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
                   'Access-Control-Request-Headers': 'Authorization,Content-Type,X-Cycle-ID,X-Received-At'}
        response = self.client.options('/api/v1/gateway/ingest', headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')
        self.assertNotIn('access-control-allow-credentials', response.headers)
        response = self.client.options('/api/v1/gateway/ingest', headers={**headers, 'Origin': 'https://untrusted.test'})
        self.assertEqual(response.status_code, 400)
        with self.assertRaises(ValueError):
            create_app(self.path, settings=replace(self.settings, cors_origins=('*',)))

    def test_history_seed_is_non_destructive_and_idempotent(self):
        first = seed_history(self.database, periods=4, now=self.received_at)
        second = seed_history(self.database, periods=4, now=self.received_at)
        self.assertEqual(first['accepted'], 80)
        self.assertEqual(second['accepted'], 0)
        self.assertEqual(second['duplicates'], 80)
        self.assertEqual(self.count('telemetry'), 80)
        self.assertEqual(self.count('fire_alerts'), 0)

    def test_concurrent_wal_ingestion(self):
        def writer(_):
            result = self.database.ingest(self.packet(), cycle_id=str(uuid4()), received_at=self.received_at)
            self.assertEqual(len(self.database.latest_readings()), 20)
            return result['accepted']
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(list(executor.map(writer, range(8))), [[1]] * 8)
        self.assertEqual(self.count('telemetry'), 8)

    def test_contract_sha256_unchanged(self):
        self.assertEqual(sha256((ROOT / '.contracts' / '02_system_contract.json').read_bytes()).hexdigest().upper(),
                         'B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356')


class IDWTests(unittest.TestCase):
    def test_inverse_square_weights_and_exact_source(self):
        self.assertAlmostEqual(idw_value(0, 0, [(1, 0, 0), (2, 0, 100)]), 20)
        self.assertEqual(idw_value(1, 0, [(1, 0, 42), (2, 0, 100)]), 42)
        self.assertEqual(idw_value(1.0005, 0, [(1, 0, 42), (2, 0, 100)]), 42)
        with self.assertRaises(ValueError):
            idw_value(0, 0, [])

    def test_projection_uses_meters_and_is_reversible(self):
        lat, lon = to_wgs84(22, 88)
        east, north = to_local(lat, lon)
        self.assertAlmostEqual(east, 22, places=6)
        self.assertAlmostEqual(north, 88, places=6)

    def test_latest_invalid_or_expired_source_is_excluded(self):
        now = utc_now()
        node = CONTRACT['topology']['nodes'][0]
        row = {**node, **CONTRACT['samples']['raw'], 'received_unix': now.timestamp()}
        self.assertEqual(generate_heatmap([row], 'soil_moisture', now=now)['source_count'], 1)
        invalid = {**row, 'soil_moisture': 0, 'status_flags': SYNTHETIC | (1 << 1),
                   'received_unix': now.timestamp() + 1}
        self.assertEqual(generate_heatmap([row, invalid], 'soil_moisture', now=now)['source_count'], 0)
        expired = {**row, 'received_unix': now.timestamp() - 3601}
        future = {**row, 'received_unix': now.timestamp() + 6}
        self.assertEqual(generate_heatmap([expired, future], 'soil_temp', now=now)['points'], [])

    def test_grid_preserves_physical_values_separate_from_heat_intensity(self):
        now = utc_now()
        row = {**CONTRACT['topology']['nodes'][0], **CONTRACT['samples']['raw'],
               'received_unix': now.timestamp()}
        result = generate_heatmap([row], 'soil_temp', grid_m=22, now=now)
        self.assertEqual(len(result['points']), 81)
        for point, value in zip(result['points'], result['values']):
            self.assertAlmostEqual(value[2], 21.5)
            self.assertAlmostEqual(point[2], (21.5 + 10) / 70)
        with self.assertRaises(ValueError):
            generate_heatmap([row], 'soil_temp', grid_m=12)


if __name__ == '__main__':
    unittest.main()
