"""IDW p=2 en metros; coordenadas locales sinteticas, no geodesia de precision."""

from __future__ import annotations

import math
from datetime import datetime

from src.backend.database import utc_now, utc_text
from src.simulator.binary_protocol import CONTRACT, SYNTHETIC

RADIUS_M = 6378137
GATEWAY = CONTRACT['topology']['gateway']
LAYERS = {
    'soil_moisture': ('%', 0, 100),
    'soil_temp': ('degC', -10, 60),
    'amb_temp': ('degC', -10, 60),
    'gas_smoke_ppm': ('ppm_synthetic', 0, 1000),
    'thermal_risk': ('index_0_1', 0, 1),
}


def clamp(value: float, low: float = 0, high: float = 1) -> float:
    return max(low, min(high, value))


def to_local(lat: float, lon: float) -> tuple[float, float]:
    return (math.radians(lon - GATEWAY['lon']) * RADIUS_M * math.cos(math.radians(GATEWAY['lat'])),
            math.radians(lat - GATEWAY['lat']) * RADIUS_M)


def to_wgs84(east: float, north: float) -> tuple[float, float]:
    return (GATEWAY['lat'] + math.degrees(north / RADIUS_M),
            GATEWAY['lon'] + math.degrees(east / (RADIUS_M * math.cos(math.radians(GATEWAY['lat'])))))


def idw_value(east: float, north: float, sources: list[tuple[float, float, float]]) -> float:
    """Fuentes (east_m,north_m,valor); coincidencia <=1 mm retorna valor exacto."""
    if not sources:
        raise ValueError('IDW requiere al menos una fuente.')
    if not all(math.isfinite(value) for value in (east, north, *(v for source in sources for v in source))):
        raise ValueError('IDW requiere coordenadas y valores finitos.')
    distances = []
    for source_east, source_north, value in sources:
        distance = math.hypot(east - source_east, north - source_north)
        if distance <= 0.001:
            return value
        if not math.isfinite(distance):
            raise ValueError('Distancia IDW fuera de rango numerico.')
        distances.append((distance, value))
    closest = min(distance for distance, _ in distances)
    # Factor comun no cambia p=2 y evita underflow/overflow de d**2.
    weighted = [((closest / distance) ** 2, value) for distance, value in distances]
    return math.fsum(weight * value for weight, value in weighted) / math.fsum(weight for weight, _ in weighted)


def source_value(row: dict, layer: str) -> float | None:
    flags = row.get('status_flags')
    if type(flags) is not int or not 0 <= flags <= 255:
        return None
    field_bits = {'soil_temp': ('soil_temp_x10', 0, 10),
                  'soil_moisture': ('soil_moisture', 1, 100),
                  'amb_temp': ('amb_temp_x10', 2, 10),
                  'gas_smoke_ppm': ('gas_smoke_ppm', 4, 1)}
    if layer == 'thermal_risk':
        ambient = source_value(row, 'amb_temp')
        gas = source_value(row, 'gas_smoke_ppm')
        return None if ambient is None or gas is None else max(clamp((ambient - 30) / 30), clamp(gas / 300))
    field, bit, scale = field_bits[layer]
    raw = row.get(field)
    limits = {'soil_temp_x10': (-550, 1250), 'soil_moisture': (0, 10000),
              'amb_temp_x10': (-400, 800), 'gas_smoke_ppm': (0, 1000)}
    if flags & (1 << bit) or type(raw) is not int or not limits[field][0] <= raw <= limits[field][1]:
        return None
    if layer == 'gas_smoke_ppm' and not flags & SYNTHETIC:
        return None
    return raw / scale


def generate_heatmap(readings: list[dict], layer: str, *, grid_m: int = 11,
                     now: datetime | None = None) -> dict:
    if layer not in LAYERS:
        raise ValueError('Capa desconocida.')
    if isinstance(grid_m, bool) or grid_m not in (11, 22):
        raise ValueError('grid_m debe ser 11 o 22.')
    now = now or utc_now()
    utc_text(now)
    # Una muestra por nodo ANTES de evaluar invalidez: no rescatar valores viejos.
    latest = {}
    for row in readings:
        timestamp = row.get('received_unix')
        node_id = row.get('node_id')
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp > now.timestamp() + 5:
            continue
        if type(node_id) is not int or node_id not in range(1, 21):
            continue
        if node_id not in latest or timestamp > latest[node_id]['received_unix']:
            latest[node_id] = row
    sources = []
    for row in latest.values():
        value = source_value(row, layer)
        if value is None or now.timestamp() - row['received_unix'] > 3600:
            continue
        lat, lon = row.get('lat'), row.get('lon')
        if (type(lat) not in (int, float) or type(lon) not in (int, float)
                or not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            continue
        east, north = to_local(row['lat'], row['lon'])
        sources.append((east, north, value))
    unit, low, high = LAYERS[layer]
    points, values = [], []
    if sources:
        for north in range(-88, 89, grid_m):
            for east in range(-88, 89, grid_m):
                value = idw_value(east, north, sources)
                lat, lon = to_wgs84(east, north)
                points.append([lat, lon, clamp((value - low) / (high - low))])
                values.append([lat, lon, value])
    return {'mode': 'simulation', 'layer': layer, 'unit': unit, 'grid_m': grid_m,
            'bbox': CONTRACT['heatmap']['bbox']['wgs84_west_south_east_north'],
            'generated_at': utc_text(now), 'source_count': len(sources),
            'points': points, 'values': values,
            'notice': 'Datos sinteticos; thermal_risk no es probabilidad ni detector certificado.'}
