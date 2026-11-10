"""Paridad real con objetos ELF Xtensa; no confunde compilacion con prueba RF.

Las pruebas portables (ctypes/tipos/pines/contrato) no requieren PlatformIO. Las
pruebas compiladas usan su toolchain si esta instalado; ninguna placa se flashea.
"""

import configparser
import ctypes
import importlib.util
import io
import json
import os
import random
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from urllib.error import URLError

from src.simulator.binary_protocol import (
    CONTRACT, FIRE_TRIGGERED, GAS_INVALID, SYNTHETIC, Header, MessageType,
    NodeReading, ProtocolError, pack_packet, unpack_packet,
)

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / 'src/firmware-esp32'
HEADER = (FIRMWARE / 'include/protocol.h').read_text(encoding='utf-8')
PINS = (FIRMWARE / 'include/hardware_pins.h').read_text(encoding='utf-8')
TYPES = {'uint8_t': ctypes.c_uint8, 'int16_t': ctypes.c_int16, 'uint16_t': ctypes.c_uint16}


def declared_fields(name):
    blocks = re.findall(r'typedef struct __attribute__\(\(packed\)\)\s*\{([^}]+)\}\s*(\w+);', HEADER)
    body = next(body for body, label in blocks if label == name)
    return re.findall(r'(uint8_t|int16_t|uint16_t)\s+(\w+)\s*;', body)


def ctype_for(name):
    return type(name, (ctypes.LittleEndianStructure,),
                {'_pack_': 1, '_fields_': [(field, TYPES[kind]) for kind, field in declared_fields(name)]})


def compiler_path():
    configured = os.environ.get('VITISCAN_CXX')
    if configured:
        return Path(configured)
    pio = Path(os.environ.get('PLATFORMIO_CORE_DIR', Path.home() / '.platformio'))
    matches = list((pio / 'packages').glob('toolchain-xtensa-esp32*/bin/xtensa-esp32-elf-g++*'))
    return matches[0] if matches else None


def elf_sections(payload):
    if payload[:6] != b'\x7fELF\x01\x01':
        raise ValueError('Se esperaba ELF32 little-endian Xtensa.')
    offset = struct.unpack_from('<I', payload, 32)[0]
    stride, count, strings_index = struct.unpack_from('<HHH', payload, 46)
    sections = [struct.unpack_from('<10I', payload, offset + i * stride) for i in range(count)]
    strings = sections[strings_index]
    names = payload[strings[4]:strings[4] + strings[5]]
    return {names[section[0]:].split(b'\0', 1)[0].decode('ascii'): payload[section[4]:section[4] + section[5]]
            for section in sections}


class FirmwareLayoutTests(unittest.TestCase):
    def setUp(self):
        self.sample = NodeReading(**CONTRACT['samples']['raw'])

    def test_header_field_order_unsigned_bytes_and_size(self):
        self.assertEqual(declared_fields('PacketHeader'), [('uint8_t', name) for name in
                         ('magic', 'msg_type', 'level', 'sender_id', 'parent_id', 'reading_count')])
        self.assertEqual(ctypes.sizeof(ctype_for('PacketHeader')), 6)
        self.assertRegex(HEADER, r'static_assert\(sizeof\(PacketHeader\) == 6,')

    def test_reading_signedness_order_offsets_and_size(self):
        fields = [('uint8_t', 'node_id'), ('int16_t', 'soil_temp_x10'), ('uint16_t', 'soil_moisture'),
                  ('int16_t', 'amb_temp_x10'), ('uint8_t', 'amb_humidity'), ('uint16_t', 'gas_smoke_ppm'),
                  ('uint8_t', 'battery_pct'), ('uint8_t', 'status_flags')]
        self.assertEqual(declared_fields('NodeReading'), fields)
        reading = ctype_for('NodeReading')
        self.assertEqual(ctypes.sizeof(reading), 12)
        self.assertEqual([getattr(reading, name).offset for _, name in fields], [0, 1, 3, 5, 7, 8, 10, 11])
        self.assertRegex(HEADER, r'static_assert\(sizeof\(NodeReading\) == 12,')

    def test_message_codes_maximum_and_little_endian_guard(self):
        for name, value in (('BEACON', 1), ('CASCADE_DATA', 2), ('ACK', 3), ('FIRE_ALERT', 255)):
            code = re.search(rf'\b{name}\s*=\s*(0x[0-9A-Fa-f]+)', HEADER).group(1)
            self.assertEqual(int(code, 16), value)
        self.assertRegex(HEADER, r'MAX_PAYLOAD_BYTES\s*=\s*246')
        self.assertRegex(HEADER, r'MAX_READINGS\s*=\s*20')
        self.assertIn('__ORDER_LITTLE_ENDIAN__', HEADER)

    def test_ctypes_exact_bytes_including_negative_temperatures_and_1000ppm(self):
        kind = ctype_for('NodeReading')
        for gas in (0, 450, 500, 1000):
            reading = replace(self.sample, soil_temp_x10=-550, amb_temp_x10=-400, gas_smoke_ppm=gas)
            values = [getattr(reading, name) for _, name in declared_fields('NodeReading')]
            self.assertEqual(bytes(kind(*values)), reading.pack())
        header = ctype_for('PacketHeader')(0xA5, 2, 1, 1, 0, 1)
        self.assertEqual(bytes(header) + self.sample.pack(), bytes.fromhex(CONTRACT['samples']['radio_data_hex']))

    def test_adc1_pins_channels_and_no_adc2_reads(self):
        for name, value in (('SOIL_MOISTURE_GPIO', 34), ('MQ2_ANALOG_GPIO', 35),
                            ('SOIL_ADC1_CHANNEL', 6), ('MQ2_ADC1_CHANNEL', 7),
                            ('ONEWIRE_GPIO', 4), ('I2C_SDA_GPIO', 21), ('I2C_SCL_GPIO', 22)):
            self.assertRegex(PINS, rf'\b{name}\s*=\s*{value}\s*;')
        source = (FIRMWARE / 'common/board_sensors.cpp').read_text()
        self.assertIn('adc1_get_raw(ADC1_CHANNEL_6)', source)
        self.assertIn('adc1_get_raw(ADC1_CHANNEL_7)', source)
        self.assertNotRegex(source, r'\badc2_get_raw\s*\(|\banalogRead\s*\(')

    def test_heater_is_digital_gate_and_real_gas_stays_invalid(self):
        gate = int(re.search(r'MQ2_HEATER_MOSFET_GPIO\s*=\s*(\d+)', PINS).group(1))
        self.assertNotIn(gate, (34, 35, 36, 39))
        source = (FIRMWARE / 'common/board_sensors.cpp').read_text()
        self.assertIn('digitalWrite(pins::MQ2_HEATER_MOSFET_GPIO', source)
        self.assertIn('latest.gas_smoke_ppm = 0; latest.status_flags |= FLAG_GAS_INVALID;', source)

    def test_platformio_two_targets_and_fail_closed_defaults(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(FIRMWARE / 'platformio.ini')
        self.assertEqual(config['env']['platform'], 'espressif32@6.12.0')
        self.assertIn('node_sensor/main.cpp', config['env:node_sensor']['build_src_filter'])
        self.assertIn('gateway_node/main.cpp', config['env:gateway_node']['build_src_filter'])
        self.assertIn('VITISCAN_BENCH_EXTERNAL_SYNC=0', config['env']['build_flags'])
        self.assertIn('VITISCAN_RF_TIMING_VALIDATED=0', config['env']['build_flags'])

    def test_beacon_not_used_as_timestamp_and_no_hidden_radio_fields(self):
        fields = [name for _, name in declared_fields('PacketHeader')]
        self.assertEqual(len(fields), 6)
        self.assertFalse(any(name in fields for name in ('timestamp', 'epoch', 'ttl', 'sequence')))
        source = (FIRMWARE / 'node_sensor/main.cpp').read_text()
        self.assertIn('if (header.msg_type == BEACON) continue;', source)

    def test_contract_hash_unchanged(self):
        self.assertEqual(sha256((ROOT / '.contracts/02_system_contract.json').read_bytes()).hexdigest().upper(),
                         'B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356')

    def test_dependency_patch_fixes_directives_without_hiding_warnings(self):
        spec = importlib.util.spec_from_file_location('vitiscan_dependency_patch', FIRMWARE / 'tools/patch_dependencies.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        approved = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(prefix='vitiscan-vendor-', dir=approved if approved.is_dir() else None) as folder:
            source = Path(folder) / 'OneWire.cpp'
            source.write_text('\n'.join(module.REPLACEMENTS), encoding='utf-8')
            self.assertTrue(module.patch_onewire(source))
            self.assertFalse(module.patch_onewire(source))
            self.assertIn('#  undef noInterrupts\n#  undef interrupts', source.read_text())


class FirmwareCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = compiler_path()
        if not cls.compiler:
            raise unittest.SkipTest('Instalar toolchain con python -m platformio pkg install -d src/firmware-esp32')
        approved = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' / 'opencode'
        cls.temporary = tempfile.TemporaryDirectory(prefix='vitiscan-parity-', dir=approved if approved.is_dir() else None)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.path = Path(cls.temporary.name)
        cls.sample = NodeReading(**CONTRACT['samples']['raw'])
        rng = random.Random(220035)
        cls.rows = [replace(cls.sample, node_id=i, soil_temp_x10=rng.randint(-550, 1250),
                            soil_moisture=rng.randint(0, 10000), amb_temp_x10=rng.randint(-400, 800),
                            amb_humidity=rng.randint(0, 100), gas_smoke_ppm=rng.randint(0, 1000))
                    for i in range(1, 21)]

        def row(reading):
            return '{' + ','.join(str(getattr(reading, field)) for _, field in declared_fields('NodeReading')) + '}'

        cls.fire = replace(cls.sample, node_id=16, gas_smoke_ppm=450, status_flags=SYNTHETIC | FIRE_TRIGGERED)
        source = '''#include "protocol.h"
#include "cascade_core.h"
#include "hardware_pins.h"
#include "sensor_math.h"
struct __attribute__((packed)) One { PacketHeader header; NodeReading reading; };
'''
        source += f'__attribute__((used,section(".parity_sample"))) const One sample = {{{{165,2,1,1,0,1}}, {row(cls.sample)}}};\n'
        source += f'__attribute__((used,section(".parity_fire"))) const One fire = {{{{165,255,1,1,255,1}}, {row(cls.fire)}}};\n'
        source += '__attribute__((used,section(".parity_max"))) const RadioPacket maximum = {{165,2,1,1,0,20},{' + ','.join(map(row, cls.rows)) + '}};\n'
        source += '__attribute__((used,section(".parity_beacon"))) const PacketHeader beacon = {165,1,0,0,255,0};\n'
        source += '__attribute__((used,section(".parity_ack"))) const PacketHeader ack = {165,3,0,0,1,0};\n'
        # El compilador evalua los validadores C++ contra los mismos casos que Python.
        cases = [cls.sample, cls.fire, replace(cls.sample, gas_smoke_ppm=1001),
                 replace(cls.sample, status_flags=0), replace(cls.sample, battery_pct=101),
                 replace(cls.sample, gas_smoke_ppm=0, status_flags=GAS_INVALID),
                 replace(cls.sample, status_flags=SYNTHETIC | GAS_INVALID),
                 replace(cls.sample, soil_temp_x10=-551), *cls.rows]
        for i, reading in enumerate(cases):
            try:
                reading.validate()
                expected = 1
            except ProtocolError:
                expected = 0
            source += f'constexpr NodeReading r{i} = {row(reading)}; static_assert(bool(protocol_valid_reading(&r{i})) == {expected}, "reading {i}");\n'
        source += '''
constexpr bool schedule() {
    for (uint8_t id=1; id<=20; ++id) {
        auto data=cascade::dataWindow(id), tx=cascade::alertTx(id);
        if (data.end-data.begin!=39 || data.end>1200 || tx.end-tx.begin!=1 || tx.begin<1200 || tx.end>1420) return false;
        if (!cascade::receiverListen(protocol_level(id)).contains(tx.begin)) return false;
        if (cascade::senderListen(protocol_level(id)).contains(tx.begin)) return false;
    } return true;
}
constexpr bool failover() {
    cascade::ParentTable p{};
    p.observe(6,1,-60,100); p.observe(6,2,-70,100); p.observe(6,3,-70,100);
    p.observe(6,6,-10,100); // mismo nivel prohibido
    p.observe(6,4,-86,100); // sensibilidad insuficiente
    if(p.seen[4].valid || p.seen[6].valid) return false;
    p.epochBoundary(100); if(p.primary!=1 || p.backup!=2) return false;
    p.failedAttempts=3; if(p.primary!=1) return false; // no cambio dentro del epoch
    p.epochBoundary(200); if(p.primary!=2 || p.backup!=1) return false;
    p.epochBoundary(900100); if(p.primary!=2 || p.backup!=255) return false;
    p.failedAttempts=3; p.epochBoundary(900101); return p.primary==255;
}
constexpr bool alertBounds() {
    cascade::AlertCache cache{}; NodeReading r={16,215,4230,287,62,450,95,192};
    cache.add(r,100); auto *entry=cache.pending(100);
    if(!entry) return false;
    entry->transmissions=3; cache.add(r,1600);
    if(cache.pending(1600)) return false;
    if(cache.entries[0].firstSeen!=100) return false;
    cache.add(r,120101); return cache.pending(120101)!=nullptr;
}
constexpr bool aggregation() {
    cascade::ReadingSet set{}; NodeReading r={1,215,4230,287,62,120,95,128};
    if(!set.add(r)||!set.add(r)||set.count!=1) return false;
    r.gas_smoke_ppm=121; if(set.canMerge(&r,1)) return false;
    return set.count==1 && set.readings[0].gas_smoke_ppm==120;
}
static_assert(schedule(), "Slots/escucha/half-duplex");
static_assert(cascade::canStartTx(CASCADE_DATA, 1000, 8000), "DATA dispone de margen de entrada al driver");
static_assert(!cascade::canStartTx(CASCADE_DATA, 1000, 6999), "Un intento reserva 6 ms completos");
static_assert(cascade::canStartTx(FIRE_ALERT, 1235000, 1236000), "Mini-TX de alerta");
static_assert(failover(), "RSSI/timeout/epoch/orphan");
static_assert(alertBounds(), "Dedup/horizonte/limites");
static_assert(aggregation(), "Agregacion inmutable/dedup");
constexpr bool soilCalibration() {
    uint16_t value=0;
    if(sensors::soilPercent(1000,-1,-1,value)) return false;
    if(sensors::soilPercent(1000,1000,1000,value)) return false;
    if(sensors::soilPercent(-1,3000,1000,value)) return false;
    if(!sensors::soilPercent(2000,3000,1000,value)||value!=5000) return false;
    if(!sensors::soilPercent(4095,3000,1000,value)||value!=0) return false;
    return sensors::soilPercent(0,3000,1000,value)&&value==10000;
}
static_assert(soilCalibration(), "Calibracion suelo sin division por cero");
'''
        fixture = cls.path / 'parity.cpp'
        fixture.write_text(source, encoding='utf-8')
        output = cls.path / 'parity.o'
        result = subprocess.run([str(cls.compiler), '-std=gnu++17', '-Os', '-Wall', '-Wextra', '-Werror',
                                 '-I', str(FIRMWARE / 'include'), '-c', str(fixture), '-o', str(output)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError('Fixture C++ no compila:\n' + result.stdout + result.stderr)
        cls.sections = elf_sections(output.read_bytes())

    def test_real_compiled_sample_matches_python_and_contract(self):
        payload = self.sections['.parity_sample']
        self.assertEqual(payload.hex(' '), CONTRACT['samples']['radio_data_hex'])
        self.assertEqual(unpack_packet(payload)[1], (self.sample,))

    def test_real_compiled_246_bytes_twenty_readings(self):
        payload = self.sections['.parity_max']
        self.assertEqual(len(payload), 246)
        self.assertEqual(payload, pack_packet(Header(MessageType.CASCADE_DATA, 1, 1, 0, 20), self.rows))

    def test_real_compiled_fire_beacon_ack(self):
        self.assertEqual(self.sections['.parity_fire'], pack_packet(Header(MessageType.FIRE_ALERT, 1, 1, 255, 1), [self.fire]))
        self.assertEqual(self.sections['.parity_beacon'].hex(' '), CONTRACT['samples']['radio_beacon_hex'])
        self.assertEqual(self.sections['.parity_ack'].hex(' '), CONTRACT['samples']['radio_ack_hex'])

    def test_c_header_also_compiles_with_packed_size_asserts(self):
        compiler = self.compiler.with_name(self.compiler.name.replace('g++', 'gcc'))
        fixture = self.path / 'parity.c'
        fixture.write_text('#include "protocol.h"\nint check(void) { return sizeof(PacketHeader)+sizeof(NodeReading); }\n')
        result = subprocess.run([str(compiler), '-std=c11', '-Wall', '-Werror', '-I', str(FIRMWARE / 'include'),
                                 '-c', str(fixture), '-o', str(self.path / 'c-parity.o')], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


class FirmwareBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('vitiscan_serial_bridge', FIRMWARE / 'tools/serial_bridge.py')
        cls.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bridge)

    def envelope(self):
        return {'gateway_id': 'GW-00', 'mode': 'simulation', 'cycle_id': str(uuid4()),
                'received_at': datetime.now(timezone.utc).isoformat(), 'payload_hex': CONTRACT['samples']['radio_data_hex']}

    def test_uart_envelope_matches_binary_http_profile(self):
        document = self.envelope()
        self.assertEqual(self.bridge.validate_envelope(document), document)

    def test_real_mode_unknown_timestamp_and_corruption_quarantined(self):
        for changes in ({'mode': 'real'}, {'received_at': '2026-11-09T12:00:00'},
                        {'received_at': None}, {'payload_hex': '00'}, {'kind': 'quarantine'}, {'gateway_id': 'GW-01'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.bridge.validate_envelope({**self.envelope(), **changes})

    def test_token_and_transport_fail_closed_before_network(self):
        for url, token in (('http://remote.test/api/v1/gateway/ingest', 'never-send'),
                           ('http://127.0.0.1:8000/api/v1/gateway/ingest', ''),
                           ('https://remote.test/wrong-endpoint', 'never-send')):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.bridge.post_envelope(self.envelope(), url, token)

    def test_mode_cannot_disguise_real_sensor_bits_and_redirects_are_disabled(self):
        real = replace(NodeReading(**CONTRACT['samples']['raw']), gas_smoke_ppm=0, status_flags=GAS_INVALID)
        packet = pack_packet(Header(MessageType.CASCADE_DATA, 1, 1, 0, 1), [real])
        with self.assertRaises(ValueError):
            self.bridge.validate_envelope({**self.envelope(), 'payload_hex': packet.hex()})
        self.assertIsNone(self.bridge.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://other.test'))

    def test_uart_timeouts_do_not_split_a_valid_frame_between_superframes(self):
        class Source:
            chunks = iter([b'{"part":', b'', b'1}\n'])
            def readline(self, limit):
                return next(self.chunks)
        lines = self.bridge.uart_lines(Source(), continuous=True)
        self.assertEqual(next(lines), b'{"part":1}\n')
        lines.close()
        with self.assertRaises(ValueError):
            list(self.bridge.uart_lines(io.BytesIO(b'partial')))
        with self.assertRaises(ValueError):
            list(self.bridge.uart_lines(io.BytesIO(b'x' * 2049 + b'\n')))

    def test_http_bridge_retry_preserves_full_246_byte_packet_and_metadata(self):
        from fastapi.testclient import TestClient
        from src.backend.main import Settings, create_app
        approved = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(prefix='vitiscan-uart-', dir=approved if approved.is_dir() else None) as folder:
            application = create_app(Path(folder) / 'isolated.db', settings=Settings(ingest_token='test-uart-token'))
            document = self.envelope()
            rows = [replace(NodeReading(**CONTRACT['samples']['raw']), node_id=i) for i in range(1, 21)]
            packet = pack_packet(Header(MessageType.CASCADE_DATA, 1, 1, 0, 20), rows)
            document['payload_hex'] = packet.hex()
            sent = []
            with TestClient(application) as client:
                class LocalOpener:
                    def open(self, request, timeout):
                        sent.append(request.data)
                        if len(sent) == 1:
                            raise URLError('fallo transitorio de prueba')
                        response = client.post('/api/v1/gateway/ingest', content=request.data,
                                               headers=dict(request.header_items()))
                        if response.status_code != 200:
                            raise AssertionError(response.text)
                        return io.BytesIO(response.content)
                with patch.object(self.bridge, 'build_opener', return_value=LocalOpener()), patch.object(self.bridge.time, 'sleep'):
                    result = self.bridge.post_envelope(document, 'http://127.0.0.1:8000/api/v1/gateway/ingest', 'test-uart-token')
                self.assertEqual(result['accepted'], list(range(1, 21)))
                self.assertEqual(result['packet_bytes'], 246)
                self.assertEqual(sent[0], sent[1])
                stored = application.state.database.latest_readings()
                self.assertEqual([item['gas_smoke_ppm'] for item in stored], [120] * 20)


if __name__ == '__main__':
    unittest.main()
