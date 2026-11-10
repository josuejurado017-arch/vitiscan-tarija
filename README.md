# VitiScan Tarija

Prototipo de telemetría vitícola y visualización de incendios con **datos
sintéticos** del Valle Central de Tarija. **No es un detector certificado ni está
validado para despliegue físico.**

## Arranque rápido · PowerShell en `D:\desarrollo`

```powershell
.\venv\Scripts\python.exe -m src.backend.run_demo
```

Abre **http://127.0.0.1:8000**, inicializa el historial y una cascada nominal
20/20. Los cuatro botones funcionan sin copiar tokens: sesión local HttpOnly,
SameSite=Strict, Host/peer loopback y validación de Origin. Un único worker, sin
confianza en proxy headers. `--no-browser` evita abrir el navegador y
`--print-command` imprime la alternativa Uvicorn sin arrancar. Ctrl+C detiene.

Para un clon nuevo (Python 3.12 recomendado):

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m platformio pkg install -d src/firmware-esp32
```

Node.js/npm no son necesarios para usar la aplicación. CDN de Leaflet y
cartografía OpenStreetMap requieren Internet, con degradación explícita si fallan.

## Estado auditado

| Módulo | Ubicación | Estado / pruebas |
|---|---|---|
| Simulador | `src/simulator/` | Operativo: protocolo, TDMA, ACK, failover y flooding; **24** pruebas |
| Backend | `src/backend/` | Simulación: FastAPI, SQLite WAL, IDW y API; **39** pruebas |
| Dashboard | `src/frontend/` | GIS, cuatro acciones, cinco capas y HEX real; **20** pruebas |
| Firmware | `src/firmware-esp32/` | Dos targets compilados, banco sin ensayo físico; **20** pruebas de paridad/puente |

Los directorios previos `backend/VitiScan.Api/`, `frontend/`, `ai-service/` y
`docker-compose.yml` pertenecen a otra pila .NET/IA/riego, no al flujo ESP-NOW de
esta demo. No se eliminaron ni se certifican sus servicios o actuadores con esta
suite. El Compose previo también ocupa 8000: no arrancarlo simultáneamente.

## Arquitectura TDMA / GIS

- **GW-00, N0 + V-01..V-20**, cinco ramas radiales y cuatro niveles; **22 m** por
  tramo de la misma rama. Coordenadas sintéticas WGS84 alrededor de
  **−21.6485, −64.6342**, no un relevamiento del terreno.
- Radio exclusivamente binaria little-endian: **`<BBBBBB>` =6 B**, lectura
  **`<BhHhBHBB>` =12 B**, **20 lecturas / 246 B** máximo. Magic `0xA5`;
  BEACON `0x01`, DATA `0x02`, ACK `0x03`, FIRE_ALERT `0xFF`.
- Superframe **1500 ms**: cascada **N4 → N3 → N2 → N1 → Gateway** en `[0,1200)`,
  300 ms por nivel; alertas `[1200,1420)`; reserva `[1420,1500)`.
- Cuatro rondas de alerta de 55 ms, ventanas de escucha **35 ms** y mini-TX por
  rama. Nunca se interrumpe la cascada. Epoch, UTC y RSSI son externos a radio.
- Tras tres DATA sin ACK, cambio de padre al límite de epoch. Caer V-01 produce
  16/20 transitorios; **V-06 cambia su padre de V-01 a V-02** y recupera 19/20.
  No es V-01 quien cambia de identidad ni se inventa su lectura ausente.
- IDW **p=2 en metros**, coincidencia <=1 mm exacta; una última muestra por nodo,
  excluyendo canales inválidos, futuros y caducados, sin rescatar muestras viejas
  para sustituir un canal inválido. Malla de 11 m: 289 puntos; 22 m: 81 puntos.
  Canvas representa valores IDW sin sumar falsas densidades; `points` contiene
  `[lat,lon,intensidad 0..1]` y `values` conserva unidades para tooltips.

## API del perfil demo

| Método / ruta | Función |
|---|---|
| `POST /api/v1/gateway/ingest` | Trama cruda o JSON `payload_hex`, UUID externo y recepción UTC; Bearer de Gateway |
| `GET /api/v1/nodes/status` | Veinte nodos, batería, RSSI y padres operativos conocidos |
| `GET /api/v1/heatmap/{layer}` | `soil_moisture`, `amb_temp`, `soil_temp`, `gas_smoke_ppm`, `thermal_risk` |
| `GET /api/v1/alerts/fire` | Alertas activas primero, motivo y latencia solo si es conocida |
| `POST /api/v1/sim/trigger` | `cascade`, `failover`, `fire` V-16 y `restore`; UUID idempotente |
| `GET /api/v1/dashboard/config` | Gateway, temporización y autenticación, nunca secretos |

OpenAPI en `/docs`. El arranque normal `src.backend.main:app` mantiene acciones
deshabilitadas y tokens `OPERATOR_TOKEN` / `GATEWAY_INGEST_TOKEN` independientes.
CORS por lista explícita; `run_demo` habilita únicamente el perfil local de
simulación. Restaurar cierra eventos **demo**, no extingue un incendio real.

El contrato `.contracts/02_system_contract.json` permanece congelado e intacto:

```text
B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356
```

**No se afirma conformidad HTTP completa.** Las fases posteriores solicitaron
una extensión demo: gas **0..1000 sintético** frente a **0..500** del contrato,
ingesta binaria/HEX frente a `batches`, `/sim/trigger`, cookie local y polling de
500 ms. API contractual completa y modo real siguen pendientes. No reinterpretar
v1 como v2 ni cambiar el bit synthetic para aceptar sensores reales. Las
diferencias y bloqueos están registrados en [docs/AUDIT.md](docs/AUDIT.md).

## Pines ESP32 clásico

| Función | GPIO / bus | Condición |
|---|---|---|
| Humedad capacitiva | **34 / ADC1 canal 6** | <=3.3 V; solo entrada |
| MQ-2 analógico | **35 / ADC1 canal 7** | Divisor/protección si módulo entrega 5 V |
| DS18B20 | 4 / OneWire | Pull-up 4.7 kΩ a 3.3 V |
| DHT22 | 27 digital | No se utiliza su función ADC2 |
| Batería MAX17048 | SDA21 / SCL22, I2C `0x36` | Pull-ups a 3.3 V |
| Gate MOSFET calefactor | **33**, salida RTC | Fuente externa; nunca alimentar calefactor desde GPIO |
| Sincronía de banco | 32 digital | Pulso externo común cada 1500 ms |
| Gate telemetría banco | 39 entrada | Pull-down externo |
| UART USB | GPIO1 TX / GPIO3 RX | 115200, niveles de 3.3 V |

ADC2 no se usa para lecturas analógicas con Wi-Fi. MQ-2 real permanece inválido
hasta calibración: 180 s de warmup no son una curva de calibración. El calefactor
~900 mW domina consumo; el RX del firmware permanece encendido. No extrapolar
autonomía del simulador ni afirmar Deep Sleep operativo de repetidores.
BEACON no lleva reloj: TX de aplicación bloqueado por defecto, sincronía externa
de banco y futura aprobación del control físico. No se flasheó ninguna placa.

## Datos y verificación reproducible

SQLite local `data/vitiscan_tarija.db`, WAL y conexiones por operación. Seed de
96 épocas ×20 nodos: 24 h ilustrativas UTC−4. Repetir no borra datos ni duplica
historial; agrega épocas faltantes y un ciclo en vivo nuevo.

```powershell
.\venv\Scripts\python.exe src/backend/seed_tarija.py
.\venv\Scripts\python.exe tools/run_tests.py
.\venv\Scripts\python.exe -O tools/run_tests.py
.\venv\Scripts\python.exe -m platformio run -d src/firmware-esp32
```

**103/103 pruebas por modo**, sin warnings ni omisiones. El runner descubre todos
los `tests/test_*.py` y el simulador; warnings y skips no pasan inadvertidos.
Fixtures C/C++ compilados comparan bytes reales del ELF con Python. Firmware
compila con `-Werror`; el parche reproducible de OneWire corrige la causa de sus
advertencias, no las oculta.

QA visual adicional, si existen Chrome y Node (solo para pruebas):

```powershell
node tests/frontend_browser_smoke.cjs
```

Comprueba botones, failover, cinco capas, polling externo, reintento tras 503 con
la misma identidad y viewport móvil. Las pruebas usan bases temporales aisladas;
100% de pruebas aprobadas no significa cobertura total ni certificación RF.
`venv/`, caches y journals SQLite se ignoran; el entorno local no se borra.

Guías: [backend](src/backend/README.md), [dashboard](src/frontend/README.md),
[firmware, pines y consumo](src/firmware-esp32/README.md), [auditoría](docs/AUDIT.md).
