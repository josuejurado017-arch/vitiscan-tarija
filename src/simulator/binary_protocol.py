"""Layout v2 little-endian; perfil demo de gas sintetico 0..1000 ppm.

El perfil amplia solo el rango de gas del contrato congelado (0..500), que se
lee sin modificar. No declarar conformidad semantica con v2 para gas >500.
"""

from __future__ import annotations

import json
import struct
from dataclasses import astuple, dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable

CONTRACT_PATH = Path(__file__).resolve().parents[2] / '.contracts' / '02_system_contract.json'
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))
if CONTRACT['version'] != '2.0.0':
    raise RuntimeError('Este simulador requiere contrato 2.0.0; no reinterpretar tramas v1.')

HEADER_STRUCT = struct.Struct('<BBBBBB')
READING_STRUCT = struct.Struct('<BhHhBHBB')
MAGIC = 0xA5
MAX_READINGS = CONTRACT['radio']['max_readings']
MAX_PAYLOAD_BYTES = CONTRACT['radio']['max_payload_bytes']
assert HEADER_STRUCT.size == 6
assert READING_STRUCT.size == 12
assert HEADER_STRUCT.size + MAX_READINGS * READING_STRUCT.size == 246
assert 246 <= MAX_PAYLOAD_BYTES
if (struct.calcsize(CONTRACT['radio']['python_formats']['header']) != 6
        or CONTRACT['radio']['python_formats']['reading'] != READING_STRUCT.format):
    raise RuntimeError('Layouts incompatibles con el contrato.')

_MESSAGE_CODES = CONTRACT['radio']['header_fields'][1]['enum']
MessageType = IntEnum('MessageType', _MESSAGE_CODES)
_LEVELS = {0: 0, **{row['node_id']: row['level'] for row in CONTRACT['topology']['nodes']}}
SYNTHETIC = 1 << 7
FIRE_TRIGGERED = 1 << 6
GAS_INVALID = 1 << 4
SYNTHETIC_GAS_RANGE = (0, 1000)


class ProtocolError(ValueError):
    """Entrada invalida, incluso ejecutando Python con -O (sin asserts)."""


def _integer(value: int, low: int, high: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProtocolError(f'{name}: entero requerido en [{low}, {high}], recibido {value!r}')


@dataclass(frozen=True, slots=True)
class NodeReading:
    node_id: int
    soil_temp_x10: int
    soil_moisture: int
    amb_temp_x10: int
    amb_humidity: int
    gas_smoke_ppm: int
    battery_pct: int
    status_flags: int

    def validate(self) -> None:
        values = astuple(self)
        for field, value in zip(CONTRACT['radio']['reading_fields'], values):
            bounds = SYNTHETIC_GAS_RANGE if field['name'] == 'gas_smoke_ppm' else field['range']
            _integer(value, *bounds, field['name'])
        for bit, value in enumerate(values[1:7]):
            if self.status_flags & (1 << bit) and value != 0:
                raise ProtocolError(f'Canal invalido {bit}: requiere placeholder 0.')
        if not self.status_flags & SYNTHETIC and not self.status_flags & GAS_INVALID:
            raise ProtocolError('Gas sin calibracion: solo valido con bit synthetic; real requiere gas_invalid.')

    def pack(self) -> bytes:
        self.validate()
        return READING_STRUCT.pack(*astuple(self))

    @classmethod
    def unpack(cls, payload: bytes) -> NodeReading:
        if len(payload) != READING_STRUCT.size:
            raise ProtocolError('NodeReading debe tener exactamente 12 bytes.')
        reading = cls(*READING_STRUCT.unpack(payload))
        reading.validate()
        return reading


@dataclass(frozen=True, slots=True)
class Header:
    msg_type: int
    level: int
    sender_id: int
    parent_id: int
    reading_count: int
    magic: int = MAGIC

    def validate(self) -> None:
        for name in ('magic', 'msg_type', 'level', 'sender_id', 'parent_id', 'reading_count'):
            _integer(getattr(self, name), 0, 255, name)
        if self.magic != MAGIC:
            raise ProtocolError('BAD_MAGIC')
        try:
            kind = MessageType(self.msg_type)
        except ValueError as exc:
            raise ProtocolError('UNKNOWN_TYPE') from exc
        if self.sender_id not in _LEVELS or self.level != _LEVELS[self.sender_id]:
            raise ProtocolError('INVALID_ID_LEVEL')
        if self.reading_count > MAX_READINGS:
            raise ProtocolError('COUNT_OVERFLOW')
        if kind == MessageType.BEACON:
            valid = (self.sender_id, self.level, self.parent_id, self.reading_count) == (0, 0, 255, 0)
        elif kind == MessageType.CASCADE_DATA:
            valid = (self.sender_id != 0 and 1 <= self.reading_count <= MAX_READINGS
                     and _LEVELS.get(self.parent_id) == self.level - 1)
        elif kind == MessageType.ACK:
            valid = self.reading_count == 0 and _LEVELS.get(self.parent_id) == self.level + 1
        else:
            valid = self.sender_id != 0 and self.parent_id == 255 and self.reading_count == 1
        if not valid:
            raise ProtocolError('INVALID_DESTINATION_OR_TYPE_COUNT')

    def pack(self) -> bytes:
        self.validate()
        return HEADER_STRUCT.pack(self.magic, self.msg_type, self.level,
                                  self.sender_id, self.parent_id, self.reading_count)

    @classmethod
    def unpack(cls, payload: bytes) -> Header:
        if len(payload) != HEADER_STRUCT.size:
            raise ProtocolError('Header debe tener exactamente 6 bytes.')
        magic, kind, level, sender, parent, count = HEADER_STRUCT.unpack(payload)
        header = cls(kind, level, sender, parent, count, magic)
        header.validate()
        return header


def pack_packet(header: Header, readings: Iterable[NodeReading] = ()) -> bytes:
    readings = tuple(readings)
    header.validate()
    if header.reading_count != len(readings):
        raise ProtocolError('reading_count no coincide con la carga.')
    if len({reading.node_id for reading in readings}) != len(readings):
        raise ProtocolError('DUPLICATE_NODE dentro de un paquete.')
    if header.msg_type == MessageType.FIRE_ALERT and not readings[0].status_flags & FIRE_TRIGGERED:
        raise ProtocolError('FIRE_ALERT requiere fire_triggered.')
    payload = header.pack() + b''.join(reading.pack() for reading in readings)
    if len(payload) > MAX_PAYLOAD_BYTES or len(payload) != 6 + 12 * len(readings):
        raise ProtocolError('BAD_LENGTH')
    return payload


def unpack_packet(payload: bytes) -> tuple[Header, tuple[NodeReading, ...]]:
    if len(payload) < HEADER_STRUCT.size or len(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolError('BAD_LENGTH')
    header = Header.unpack(payload[:6])
    if len(payload) != 6 + 12 * header.reading_count:
        raise ProtocolError('BAD_LENGTH: carga truncada o bytes sobrantes.')
    readings = tuple(NodeReading.unpack(payload[offset:offset + 12])
                     for offset in range(6, len(payload), 12))
    # Una unica ruta de validacion para codificar y decodificar.
    pack_packet(header, readings)
    return header, readings


def fragment_readings(readings: Iterable[NodeReading], *, level: int,
                      sender_id: int, parent_id: int) -> list[bytes]:
    """Grupos independientes <=20, sin indices ocultos ni reensamblado magico.

    El receptor deduplica por node_id/epoch externo. En la topologia de 20 nodos,
    >20 entradas solo pueden ser reenvios; no son nuevas muestras del mismo ciclo.
    IDs repetidos dentro de un mismo grupo se rechazan.
    """
    readings = tuple(readings)
    if not readings:
        raise ProtocolError('CASCADE_DATA requiere al menos una lectura.')
    return [pack_packet(Header(MessageType.CASCADE_DATA, level, sender_id, parent_id, len(chunk)), chunk)
            for offset in range(0, len(readings), MAX_READINGS)
            for chunk in (readings[offset:offset + MAX_READINGS],)]
