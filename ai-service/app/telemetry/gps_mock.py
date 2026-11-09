from datetime import datetime, timezone, timedelta
from typing import List
from ..models.schemas import TelemetryWaypoint

# Coordenadas Base: Tolomosa, Valle Central de Tarija (-21.5721° S, -64.7478° W)
BASE_LAT = -21.57210
BASE_LNG = -64.74780
BASE_ELEVATION_MSNM = 1852.0  # Altitud sobre el nivel del mar en Tolomosa

# Plan de Vuelo Fotogramétrico (Grid en zigzag sobre viñedo)
FLIGHT_WAYPOINTS = [
    {"offset_lat": 0.00000, "offset_lng": 0.00000, "sector": "Tolomosa - Despegue", "agl": 20.0, "speed": 6.5, "camera": False, "event": "Despegue y calibración RTK"},
    {"offset_lat": 0.00050, "offset_lng": 0.00020, "sector": "Sector A - Hilera 1", "agl": 42.0, "speed": 11.2, "camera": True, "event": "Captura multiespectral ortofoto"},
    {"offset_lat": 0.00100, "offset_lng": 0.00022, "sector": "Sector A - Hilera 2", "agl": 42.5, "speed": 11.0, "camera": True, "event": "Follaje saludable verificado"},
    {"offset_lat": 0.00150, "offset_lng": 0.00060, "sector": "Sector B - Hilera 1", "agl": 43.0, "speed": 10.8, "camera": True, "event": "Inicio ladera central"},
    {"offset_lat": 0.00100, "offset_lng": 0.00065, "sector": "Sector B - Hilera 2", "agl": 42.2, "speed": 10.5, "camera": True, "event": "Detección: Posible estrés hídrico (GLI bajo)"},
    {"offset_lat": 0.00050, "offset_lng": 0.00070, "sector": "Sector B - Hilera 3", "agl": 41.8, "speed": 10.8, "camera": True, "event": "Inferencia IA confirma: Déficit hídrico en válvula 03"},
    {"offset_lat": 0.00050, "offset_lng": 0.00110, "sector": "Sector C - Hilera 1", "agl": 43.5, "speed": 11.4, "camera": True, "event": "Monitoreo fitosanitario"},
    {"offset_lat": 0.00100, "offset_lng": 0.00115, "sector": "Sector C - Hilera 2", "agl": 44.0, "speed": 11.2, "camera": True, "event": "Detección temprana: Sospecha Lobesia Botrana"},
    {"offset_lat": 0.00150, "offset_lng": 0.00120, "sector": "Sector C - Hilera 3", "agl": 43.8, "speed": 11.0, "camera": True, "event": "Registro de coordenadas GPS para cuadrilla"},
    {"offset_lat": 0.00080, "offset_lng": 0.00050, "sector": "Retorno RTL", "agl": 45.0, "speed": 14.0, "camera": False, "event": "Misión concluida, regreso automático a home"},
    {"offset_lat": 0.00000, "offset_lng": 0.00000, "sector": "Tolomosa - Aterrizaje", "agl": 5.0, "speed": 2.0, "camera": False, "event": "Descenso final en helipad"}
]

def get_tolomosa_flight_route() -> List[TelemetryWaypoint]:
    """
    Retorna la secuencia completa de telemetría de la misión sobre Tolomosa, Tarija.
    """
    now = datetime.now(timezone.utc)
    route = []

    for idx, wp in enumerate(FLIGHT_WAYPOINTS):
        timestamp = (now + timedelta(seconds=idx * 25)).isoformat()
        lat = round(BASE_LAT + wp["offset_lat"], 6)
        lng = round(BASE_LNG + wp["offset_lng"], 6)
        agl = wp["agl"]
        msnm = round(BASE_ELEVATION_MSNM + agl, 1)
        battery = max(20, 98 - (idx * 4))

        route.append(TelemetryWaypoint(
            paso=idx + 1,
            timestamp=timestamp,
            latitud=lat,
            longitud=lng,
            altitud_msnm=msnm,
            altitud_agl=agl,
            velocidad_ms=wp["speed"],
            bateria_pct=battery,
            sector=wp["sector"],
            disparo_camara=wp["camera"],
            evento_ia=wp.get("event")
        ))

    return route
