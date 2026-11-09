"""Pruebas sin dependencias: python -m unittest discover -s src/simulator -v."""

import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from binary_protocol import (CONTRACT, FIRE_TRIGGERED, GAS_INVALID, HEADER_STRUCT,
                             READING_STRUCT, SYNTHETIC, Header, MessageType,
                             NodeReading, ProtocolError, fragment_readings,
                             pack_packet, unpack_packet)
from cascade_network import CascadeNetwork


class BinaryTests(unittest.TestCase):
    def setUp(self):
        self.reading = NodeReading(**CONTRACT['samples']['raw'])
        self.header = Header(MessageType.CASCADE_DATA, 1, 1, 0, 1)

    def test_sizes_and_contract_sample(self):
        self.assertEqual((HEADER_STRUCT.size, READING_STRUCT.size), (6, 12))
        payload = pack_packet(self.header, [self.reading])
        self.assertEqual(payload.hex(' '), CONTRACT['samples']['radio_data_hex'])
        self.assertEqual(unpack_packet(payload), (self.header, (self.reading,)))

    def test_negative_temperatures_and_two_byte_gas(self):
        reading = replace(self.reading, soil_temp_x10=-550, amb_temp_x10=-400, gas_smoke_ppm=500)
        self.assertEqual(NodeReading.unpack(reading.pack()), reading)
        self.assertEqual(reading.pack()[8:10], b'\xf4\x01')

    def test_message_codes(self):
        self.assertEqual([int(MessageType[name]) for name in
                          ('BEACON', 'CASCADE_DATA', 'ACK', 'FIRE_ALERT')], [1, 2, 3, 255])
        beacon = pack_packet(Header(MessageType.BEACON, 0, 0, 255, 0))
        ack = pack_packet(Header(MessageType.ACK, 0, 0, 1, 0))
        self.assertEqual(beacon.hex(' '), CONTRACT['samples']['radio_beacon_hex'])
        self.assertEqual(ack.hex(' '), CONTRACT['samples']['radio_ack_hex'])

    def test_v1_archive_is_unchanged(self):
        archive = Path(__file__).resolve().parents[2] / '.contracts' / CONTRACT['supersedes']['archive']
        self.assertEqual(sha256(archive.read_bytes()).hexdigest().upper(), CONTRACT['supersedes']['sha256'])

    def test_fragmentation_boundaries(self):
        rows = [replace(self.reading, node_id=node_id) for node_id in range(1, 21)]
        for entries, lengths in ((rows[:1], [18]), (rows, [246]),
                                 (rows + rows[:1], [246, 18]),
                                 (rows * 2 + rows[:5], [246, 246, 66])):
            with self.subTest(count=len(entries)):
                packets = fragment_readings(entries, level=1, sender_id=1, parent_id=0)
                self.assertEqual([len(packet) for packet in packets], lengths)
                self.assertEqual([row for packet in packets for row in unpack_packet(packet)[1]], entries)

    def test_malformed_payloads_rejected(self):
        payload = pack_packet(self.header, [self.reading])
        bad = [b'', payload[:5], payload[:-1], payload + b'\x00', b'\x00' + payload[1:],
               payload[:1] + b'\x04' + payload[2:], payload[:5] + b'\x15' + payload[6:],
               payload[:2] + b'\x04' + payload[3:]]
        for packet in bad:
            with self.subTest(packet=packet.hex()), self.assertRaises(ProtocolError):
                unpack_packet(packet)

    def test_semantic_validation(self):
        for reading in (replace(self.reading, gas_smoke_ppm=501),
                        replace(self.reading, battery_pct=101),
                        replace(self.reading, amb_temp_x10=-401),
                        replace(self.reading, node_id=True),
                        replace(self.reading, soil_moisture=1.2),
                        replace(self.reading, status_flags=0),
                        replace(self.reading, status_flags=SYNTHETIC | GAS_INVALID)):
            with self.subTest(reading=reading), self.assertRaises(ProtocolError):
                reading.pack()
        valid_real = replace(self.reading, gas_smoke_ppm=0, status_flags=GAS_INVALID)
        self.assertEqual(NodeReading.unpack(valid_real.pack()), valid_real)

    def test_counts_duplicates_and_empty_data(self):
        with self.assertRaises(ProtocolError):
            pack_packet(replace(self.header, reading_count=2), [self.reading])
        with self.assertRaises(ProtocolError):
            pack_packet(replace(self.header, reading_count=2), [self.reading, self.reading])
        with self.assertRaises(ProtocolError):
            fragment_readings([], level=1, sender_id=1, parent_id=0)
        with self.assertRaises(ProtocolError):
            pack_packet(Header(MessageType.FIRE_ALERT, 1, 1, 255, 1), [self.reading])


class NetworkTests(unittest.TestCase):
    def test_discovery_rssi_and_topology(self):
        network = CascadeNetwork()
        network.discover()
        self.assertEqual(len(network.nodes), 21)
        for node in network.nodes.values():
            if not node.node_id:
                continue
            candidates = network._candidates(node)
            self.assertEqual(node.primary_parent, candidates[0])
            self.assertEqual(network.nodes[node.primary_parent].level, node.level - 1)
            self.assertEqual(node.backup_parent, candidates[1] if len(candidates) > 1 else None)
        self.assertTrue(all(event.sender_id == 0 for event in network.events
                            if event.kind == MessageType.BEACON))
        network.validate_trace()

    def test_complete_cascade_and_slot_boundaries(self):
        network = CascadeNetwork()
        result = network.run_cascade()
        self.assertEqual(set(result.readings), set(range(1, 21)))
        self.assertEqual(result.missing_node_ids, [])
        self.assertEqual(result.overflow_node_ids, [])
        for event in network._last_cascade_events:
            node_id = event.sender_id if event.kind == MessageType.CASCADE_DATA else event.target_id
            node = network.nodes[node_id]
            start = result.start_ms + (4 - node.level) * 300 + 15 + (node.branch - 1) * 54
            self.assertGreaterEqual(event.start_ms, start)
            self.assertLessEqual(event.end_ms, start + 39)

    def test_node_failure_changes_parent_only_after_failed_epoch(self):
        network = CascadeNetwork()
        network.run_cascade()
        old = network.nodes[11].primary_parent
        network.set_node_alive(6, False)
        self.assertEqual(network.nodes[11].primary_parent, old)
        degraded = network.run_cascade()
        self.assertEqual(degraded.missing_node_ids, [6, 11, 16])
        self.assertIn((11, 6, network.nodes[11].primary_parent), degraded.failovers)
        self.assertNotEqual(network.nodes[11].primary_parent, 6)
        attempts = [event for event in network._last_cascade_events
                    if event.sender_id == 11 and event.kind == MessageType.CASCADE_DATA]
        self.assertEqual(len(attempts), 3)
        recovered = network.run_cascade()
        self.assertEqual(recovered.missing_node_ids, [6])

    def test_all_parents_down_and_gateway_down(self):
        network = CascadeNetwork()
        network.discover()
        for node_id in range(6, 11):
            network.set_node_alive(node_id, False)
        network.run_cascade()
        self.assertTrue(all(network.nodes[node_id].primary_parent is None for node_id in range(11, 16)))
        other = CascadeNetwork()
        other.discover()
        other.set_node_alive(0, False)
        self.assertEqual(len(other.run_cascade().readings), 0)

    def test_ack_loss_retries_deduplicate(self):
        network = CascadeNetwork(ack_losses={(16, 11): 1})
        result = network.run_cascade()
        self.assertEqual(len(result.readings), 20)
        attempts = [event for event in network._last_cascade_events
                    if event.sender_id == 16 and event.kind == MessageType.CASCADE_DATA]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0].payload, attempts[1].payload)

    def test_data_loss_and_exhausted_ack(self):
        network = CascadeNetwork(data_losses={(16, 11): 1}, ack_losses={(6, 1): 3})
        result = network.run_cascade()
        self.assertEqual(len(result.readings), 20)  # Datos recibidos aunque se pierdan ACK.
        self.assertTrue(any(node_id == 6 for node_id, _, _ in result.failovers))

    def test_flooding_windows_dedup_and_bounds(self):
        network = CascadeNetwork()
        network.run_cascade()
        reading = network.trigger_fire(16)
        result = network.run_fire_alerts(5)
        self.assertEqual(len(result), 1)
        self.assertIn(reading.pack(), result)
        for event in network.events:
            if event.kind != MessageType.FIRE_ALERT:
                continue
            self.assertEqual(len(event.payload), 18)
            self.assertEqual(unpack_packet(event.payload)[1], (reading,))
            for receiver in event.received_by:
                self.assertTrue(any(window.node_id == receiver and window.start_ms <= event.start_ms
                                    and event.end_ms <= window.end_ms for window in network.listen_windows))
            self.assertFalse(any(window.node_id == event.sender_id
                                 and window.start_ms < event.end_ms and event.start_ms < window.end_ms
                                 for window in network.listen_windows))
        for cache in network.alert_cache.values():
            self.assertTrue(all(entry.transmissions <= 3 for entry in cache.values()))
        count = len([event for event in network.events if event.kind == MessageType.FIRE_ALERT])
        network.run_fire_alerts(2)
        self.assertEqual(count, len([event for event in network.events if event.kind == MessageType.FIRE_ALERT]))

    def test_fire_detection_validity_and_temperature_delta(self):
        network = CascadeNetwork()
        reading = network.sample(1)
        self.assertFalse(network.detects_fire(reading))
        self.assertTrue(network.detects_fire(replace(reading, gas_smoke_ppm=300)))
        invalid = replace(reading, gas_smoke_ppm=0, status_flags=SYNTHETIC | GAS_INVALID)
        self.assertFalse(network.detects_fire(invalid))
        hot = replace(reading, amb_temp_x10=reading.amb_temp_x10 + 80)
        self.assertTrue(network.detects_fire(hot, reading, 45))
        self.assertFalse(network.detects_fire(hot, reading, 61))

    def test_two_fire_origins_and_down_relays(self):
        network = CascadeNetwork()
        network.run_cascade()
        network.set_node_alive(11, False)
        first = network.trigger_fire(16)
        second = network.trigger_fire(17)
        result = network.run_fire_alerts(4)
        self.assertIn(first.pack(), result)
        self.assertIn(second.pack(), result)
        self.assertTrue(all(event.sender_id != 11 for event in network.events if event.phase == 'alert'))

    def test_battery_parallel_and_heater(self):
        network = CascadeNetwork()
        network.run_cascade()
        single = network.battery_report(1)
        parallel = network.battery_report(1, 2)
        self.assertAlmostEqual(parallel['electronics_days'], 2 * single['electronics_days'])
        self.assertAlmostEqual(parallel['with_heater_days'], 2 * single['with_heater_days'])
        self.assertLess(single['with_heater_days'], single['electronics_days'])
        self.assertGreater(single['alert_rx_duty_pct'], network.battery_report(16)['alert_rx_duty_pct'])
        with self.assertRaises(ValueError):
            network.battery_report(1, telemetry_interval_s=901)


if __name__ == '__main__':
    unittest.main()
