# Backend demo — VitiScan Tarija

Python 3.11+, FastAPI y SQLite; IDW utiliza solo `math` y biblioteca estándar.
**Datos exclusivamente sintéticos**, no son mediciones meteorológicas ni una alerta
de seguridad certificada. No utiliza radio, servicios externos ni datos reales.

## Arranque desde `D:\desarrollo`

Las dependencias ya están instaladas en `venv`. Para otro entorno:

```powershell
.\venv\Scripts\python.exe -m pip install -r src/backend/requirements.txt
.\venv\Scripts\python.exe src/backend/seed_tarija.py

$env:APP_MODE = 'simulation'
$env:GATEWAY_INGEST_TOKEN = '<secreto-de-ingesta>'
$env:OPERATOR_TOKEN = '<otro-secreto-para-operador>'
$env:SIM_ACTIONS_ENABLED = 'true'
$env:CORS_ALLOWED_ORIGINS = 'http://localhost:5173,http://localhost:4200'
.\venv\Scripts\python.exe -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8000
```

OpenAPI en `http://127.0.0.1:8000/docs`. CORS parte de una lista vacía, sin `*`
ni credenciales del navegador. Las acciones están **deshabilitadas por defecto**.
Ingesta requiere Bearer de Gateway; las acciones requieren Bearer independiente de
operador. Sin secretos configurados se rechaza el acceso. Lecturas públicas solo
en simulación; `mode=real` y `APP_MODE=real` no están soportados. No publicar fuera
de localhost sin HTTPS, límites de acceso y controles operativos adicionales.

La base por defecto es `data/vitiscan_tarija.db`, relativa al proyecto, no al cwd.
Puede cambiarse con `VITISCAN_DB_PATH`. WAL, `foreign_keys`, timeout de 10 s y
`synchronous=FULL`; conexiones por operación, sin compartir conexiones entre hilos.
Inicialización no destructiva; tablas `nodes`, `telemetry`, `fire_alerts` y
`simulation_runs`. Índices y consulta de ventana para última lectura, sin N+1.

## Perfil HTTP solicitado y contrato congelado

`.contracts/02_system_contract.json` se lee **sin modificaciones**. Se reutiliza
`src/simulator/binary_protocol.py`: `<BBBBBB>` de 6 B y `<BhHhBHBB>` de 12 B,
máximo 20 lecturas/246 B. Ningún timestamp, epoch, RSSI, latencia o índice de
fragmento se añade a los bytes de radio.

**Esta fase implementa una extensión demo, no el contrato HTTP JSON v2 completo:**
la ingesta de hex/binario, `/nodes/status`, `/sim/trigger`, las capas `amb_temp` y
`gas_smoke_ppm`, y el campo adicional `values` son la interfaz solicitada en esta
fase. No se implementan aquí las acciones asíncronas `/actions/*` ni la ingesta
`batches` del contrato. El perfil del simulador admite gas sintético **0–1000**;
el contrato permanece en **0–500**. Valores >500 no son conformes a esa ingesta
contractual. El escenario de incendio del puente usa **450 ppm**.

### `POST /api/v1/gateway/ingest`

Con `Authorization: Bearer <GATEWAY_INGEST_TOKEN>`:

- `Content-Type: application/octet-stream`: una trama de hasta 246 B;
  encabezados HTTP obligatorios `X-Cycle-ID` (UUID externo) y `X-Received-At`
  (RFC3339 con zona, instante de recepción **en Gateway**). `X-Gateway-ID`
  opcional, solo `GW-00`. `X-Latency-Ms` opcional, referencia externa confiada.
- `Content-Type: application/json`: envoltorio del Gateway, no JSON por radio:

```json
{
  "gateway_id": "GW-00",
  "mode": "simulation",
  "cycle_id": "00000000-0000-4000-8000-000000000001",
  "received_at": "2026-11-09T18:00:00Z",
  "payload_hex": "a5 02 01 01 00 01 01 d7 00 86 10 1f 01 3e 78 00 5f 80"
}
```

Use el instante real de recepción del Gateway, no copie el timestamp del ejemplo.
`latency_ms` es opcional en JSON. Sin referencia externa se almacena `null`, nunca
se inventa una latencia cero ni se supone recepción en ventana de 35 ms. El puente
sí aporta reloj virtual, fase de recepción, ventana real y latencia de inyección
a recepción, marcadas como `simulator_external`. El backend no puede verificar
por sí solo el horario RF de una trama recibida por HTTP.

Solo DATA destinado al Gateway y FIRE_ALERT se guardan como muestras. BEACON/ACK
son control, no telemetría. Se validan longitud, magic, tipo, campos, IDs, flags y
duplicados con el decodificador compartido. **No hay CRC/MAC criptográfico:** una
alteración que siga siendo estructuralmente válida no es detectable aquí.

Identidad `UNIQUE(gateway_id,cycle_id,node_id)`: repetir mismos bytes, timestamp y
metadatos devuelve `duplicates`; cambiar contenido da **409 y rollback de toda
la trama**, incluidas alertas. Los reintentos deben conservar sus metadatos.
Cada trama es transaccional, pero un escenario de múltiples tramas no es una única
transacción. Si el proceso falla a mitad, puede existir un escenario parcial.
Errores estructurales 422, JSON inválido 400, cuerpo grande 413, tipo no admitido
415, SQLite no disponible 503. La respuesta de éxito se emite después de commit.

`critical=true` si el tipo es `0xFF` (aunque gas no supere umbral) o si gas **válido
>=300 ppm sintéticos**. Gas inválido no dispara por gas. Las réplicas se unen por
origen/12 bytes dentro de 120 s; después de 120 s sin recepción, `inactive` **no
significa incendio extinguido**. Esta fase no evalúa delta temporal de temperatura
en la ingesta; el simulador conserva su propia lógica de detección.

### Lecturas

- `GET /api/v1/nodes/status`: siempre 20 nodos; coordenadas/nivel y padres semilla,
  `operational_parent_id`, `operational_backup_id`, batería, RSSI y
  `failover`/`using_backup_parent`. Padres operativos/RSSI quedan `null` sin
  metadatos del coordinador: no se inventan desde un paquete agregado. El fallo
  conocido por el simulador se expresa `offline`; sin muestra durante 3600 s,
  `stale`. Batería inválida se devuelve `null`.
- `GET /api/v1/topology`: alias demo de estado.
- `GET /api/v1/alerts/fire`: eventos, motivo, estado y latencia externa si existe.
- `GET /api/v1/heatmap/{layer}?grid_m=11`: `soil_moisture`, `soil_temp`, `amb_temp`,
  `gas_smoke_ppm`, `thermal_risk`. `grid_m=22` produce 81 puntos; 11 produce 289.

IDW **p=2 en metros**, proyección local coherente con Tarija; a <=1 mm de una fuente
devuelve su valor exacto. Una última muestra por nodo/capa, máximo 20; excluir datos
>3600 s o >5 s en el futuro y canales inválidos, sin recuperar muestras anteriores
para sustituir un canal actualmente inválido. Sin fuentes devuelve malla vacía.

`points` contiene **[lat, lon, intensidad 0..1]**, listo para `Leaflet.heat`;
`values` contiene **[lat, lon, valor físico/sintético]** para tooltip/leyenda.
Suelo: centésimas de % -> %; temperaturas: décimas -> °C. Intensidades: humedad/100,
temperatura `(C+10)/70`, gas sintético/1000, todas limitadas a 0..1. `thermal_risk`
usa por nodo `max(clamp((amb_C-30)/30),clamp(gas/300))` antes de IDW; no es una
probabilidad ni determina por sí solo una alerta.

### `POST /api/v1/sim/trigger`

Con Bearer de operador y acciones habilitadas:

```json
{"action": "failover", "idempotency_key": "00000000-0000-4000-8000-000000000002"}
```

- `cascade`: cascada 20/20.
- `failover`: 20/20 inicial, caída V-01 (16/20), conmutación V-06 a V-02 y
  recuperación 19/20. Solo V-01 falta; estado final `partial`.
- `fire`: incendio de 450 ppm sintéticos en V-16, flooding real del simulador,
  ventanas de 35 ms fuera de `[0,1200)` y entrega deduplicada en Gateway.

Escenarios **independientes**, no mantienen caídas entre llamadas. Se ingieren
solo `RadioEvent.payload` realmente recibidos por nodo 0, no se simula entrega
desde una lista de resultados. La respuesta incluye HEX real y validación de
half-duplex/slots. No espera tiempo de pared y responde sin cola asíncrona.
Usar un único worker para la demo; lock por proceso. Claves de idempotencia
persistentes devuelven el mismo resultado; otra acción con la misma clave da 409.
Clave en curso/interrumpida da 409: revisar estado parcial y usar una nueva.
Las claves completadas se conservan, sin purga automática en esta fase.

## Seed y pruebas

Seed por defecto: 96 épocas/24 h, 20 nodos, hora local UTC-4, ciclos diurnos y
variación espacial determinista. Es un historial **climáticamente ilustrativo**,
no datos observados ni modelo validado del Valle Central de Tarija. Repetir seed
no borra datos ni duplica instantes históricos. Cada ejecución añade una corrida
en vivo nueva e independiente. Opciones: `--periods 4 --live fire --db <ruta>`.

```powershell
.\venv\Scripts\python.exe src/backend/seed_tarija.py
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m unittest discover -s src/simulator -v
```

Las pruebas usan bases temporales aisladas; no cambian `data/vitiscan_tarija.db`.
Incluyen el SHA-256 del contrato, tramas reales, corrupción, rollback,
concurrencia WAL, IDW, failover V-01 y flooding V-16 con latencia/escucha verificadas.
