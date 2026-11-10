# Firmware ESP32 — VitiScan Tarija (banco experimental)

Dos targets **ESP32 clásico / esp32dev**, Arduino-ESP32 2.0.17 y ESP-NOW v1,
PlatformIO `espressif32@6.12.0`. No se ha flasheado ni validado RF en una placa.
**Prototipo no certificado; NO desplegar como detector de incendios.**

## Límite de arquitectura: BEACON no transporta reloj

Se conserva `.contracts/02_system_contract.json` byte a byte. Su BEACON de **6 B**
anuncia presencia de Gateway, **no reloj**. Ni la cabecera ni las lecturas admiten
timestamp, epoch, TTL o secuencia ocultos. No es posible obtener sincronización
inequívoca de 20 nodos a cuatro saltos únicamente con ese BEACON.

Esta entrega es firmware **compilable y de banco**, no una solución del bloqueo
físico señalado por el contrato. Por defecto **NO encola tramas ESP-NOW de aplicación**.
Esto no desactiva respuestas automáticas MAC del driver Wi-Fi. El banco propone
un pulso externo común en GPIO32 y gate de telemetría en GPIO39; estos cables y
comandos UART son control externo, **no parte de radio ni un contrato nuevo
aprobado para producción**. Un despliegue físico requiere revisión autorizada del
control/sincronización, validación de deriva, wakeup, pérdidas y anti-replay.

Dos flags independientes bloquean TX: `VITISCAN_BENCH_EXTERNAL_SYNC=0` y
`VITISCAN_RF_TIMING_VALIDATED=0`. No basta cambiar flags para validar hardware.
El segundo es una confirmación del operador después de medir el banco, no una
certificación automática. Sensores sintéticos habilitados explícitamente en los
targets de demostración; calefactor y Deep Sleep deshabilitados por defecto.

## Compilar desde `D:\desarrollo`

```powershell
.\venv\Scripts\python.exe -m pip install platformio
.\venv\Scripts\python.exe -m platformio run -d src/firmware-esp32 -e node_sensor
.\venv\Scripts\python.exe -m platformio run -d src/firmware-esp32 -e gateway_node
```

`node_sensor` usa **V-16 / Nivel 4** por defecto. Cambiar `VITISCAN_NODE_ID` a 1..20
antes de compilar cada nodo; Gateway usa 0. Nivel y rama derivan del ID: cinco nodos
por nivel, cuatro niveles. La tabla MAC-ID de laboratorio es
`02:56:54:00:00:<ID en hex>`, y `FF:FF:FF:FF:FF:FF` es broadcast. No duplicar IDs
ni asumir que esa tabla representa MACs de dispositivos reales no provisionados.
Solo se añaden peers de niveles adyacentes y broadcast, dentro del límite de peers.

Comandos de upload solo tras revisar pines y placa (no ejecutados por las pruebas):

```powershell
.\venv\Scripts\python.exe -m platformio run -d src/firmware-esp32 -e node_sensor -t upload --upload-port COM3
.\venv\Scripts\python.exe -m platformio device monitor --port COM3 --baud 115200
```

## Pines / cableado ESP32 clásico

| Función | GPIO / interfaz | Requisito |
|---|---|---|
| Humedad capacitiva | **34, ADC1_CHANNEL_6** | Entrada <=3.3 V; solo entrada, sin pull-up interno |
| MQ-2 analógico | **35, ADC1_CHANNEL_7** | Divisor/protección si módulo entrega hasta 5 V; masa común |
| DS18B20 / OneWire | 4 | Pull-up 4.7 kΩ a 3.3 V; bus digital |
| DHT22 ambiente | 27 | Digital con pull-up según módulo; **no lectura ADC2** |
| I2C SDA / SCL | 21 / 22 | Pull-ups a 3.3 V |
| SOC de batería | MAX17048, I2C `0x36` | Calibración/modelo de celda a validar; no ADC ficticio |
| Gate MOSFET calefactor | **33**, salida RTC | MOSFET lógico 3.3 V, resistencia serie y pull-down de gate |
| Sincronía de banco | 32, entrada digital | Pulsos comunes 0..3.3 V cada 1500 ms |
| Gate telemetría banco | 39, entrada | Pull-down externo; alto durante el superframe de telemetría |
| Consola / puente | UART0 USB 115200 | GPIO1 TX / GPIO3 RX del DevKit; no conectar UART de 5 V |

```
Sensor capacitivo AO ── protección 3.3V ── GPIO34 ADC1
MQ-2 AO (hasta 5V) ─── divisor/protección ─ GPIO35 ADC1
MQ-2 calefactor ── fuente regulada según ficha ── MOSFET ── GND
ESP32 GPIO33 ── R gate ── gate; pull-down a GND; GND común
Controlador externo ── pulso 1500ms ── GPIO32 de TODOS los ESP32
Controlador externo ── gate telemetría ── GPIO39 de TODOS los ESP32
```

El GPIO **no alimenta el calefactor**. Usar fuente, MOSFET, protecciones y tensión
del fabricante; no alimentar un módulo MQ-2 desde una salida ESP32. GPIO34/35 son
solo entrada. **No se llama `adc2_get_raw` ni `analogRead` en ADC2** con Wi-Fi.
Que GPIO27 sea un pin multiplexado ADC2 no afecta su uso puramente digital.

## Sensores y precalentamiento

Los targets contienen `VITISCAN_SYNTHETIC_SENSORS=1`: lecturas demo identificadas
con bit 7, rango de gas sintético **0..1000** para paridad con el simulador. El
contrato congelado sigue en **0..500**, sin modificar. Inyección `FIRE`: 450 ppm
sintéticos, bit 6 y bit 7. No se deriva gas sintético del ADC real ni se publica
una curva de MQ-2 inventada.

Para el banco de sensores físicos, cambiar a `VITISCAN_SYNTHETIC_SENSORS=0`:

- ADC1 de suelo/MQ-2, OneWire asíncrono, DHT22 e I2C de batería. Muestreo a 45 s;
  adquisiciones lentas solo fuera de cascada/alertas.
- Humedad de suelo requiere `VITISCAN_SOIL_DRY_ADC` y `VITISCAN_SOIL_WET_ADC` medidos;
  sin ellos se marca inválida, placeholder 0. La escala de radio es centésimas %.
- Canales desconectados/NaN fuera de rango se marcan inválidos, nunca lecturas cero
  presentadas como medidas válidas. Temperaturas en décimas °C, signed int16.
- `VITISCAN_MQ2_HEATER_ENABLED=1` habilita el gate; mínimo ilustrativo **180000 ms**
  desde arranque. Reiniciar vuelve a iniciar warmup de forma conservadora. Ese
  mínimo no sustituye acondicionamiento del fabricante ni calibración posterior.
- Incluso después del calentamiento, gas físico sigue **`gas_invalid=1`, valor 0**.
  No dispara por gas. Delta ambiental válido >=8 °C en <=60 s puede originar alerta.

## Descubrimiento y ejecución de banco

Después de instalar flags de banco conscientemente, usar `MAINT 1` por UART **en
todos los equipos**, coordinados externamente. Este modo detiene la cascada y el
flooding operativos. Gateway emite BEACON cada 2 s; solo N1 lo usa como candidato
de nivel anterior. Nodos superiores oyen DATA/ACK de sondeo mediante un sniffer
acotado ESP-NOW v1 sin cifrar: OUI, longitud y protocolo validados, MAC-ID conocida.
RSSI proviene del driver, no de distancias ni de números inventados. El sniffer
solo observa candidatos; nunca ingiere ni ACKea su copia promiscuous.

Selección de candidatos de nivel inmediatamente anterior, RSSI >=−85 dBm,
observados en últimos 60 s; mejor RSSI y empate menor ID. Una asociación existente
se retiene durante el silencio entre telemetrías de 900 s; no se expulsa al padre
solo por falta de tráfico. Tras tres fallos sí se exige observación reciente del
reemplazo. Nodo N1 solo Gateway, sin respaldo independiente.
Los sondeos se descartan como telemetría. No mezclar equipos en mantenimiento y
otros en operación: el controlador de banco debe coordinar la transición global.

Aplicar `MAINT 0` a todos, con pulso común estable de 1.5 s y gate coordinado.
Se requieren dos pulsos consecutivos coherentes (tolerancia provisional 200 µs de
intervalo), no dos BEACONs, para permitir TX. Pérdida de pulso o lock invalida TX.
Esto **no prueba error de fase absoluto ni deriva relativa** entre dispositivos.

- Cascada `[0,1200)`, niveles **4 → 3 → 2 → 1**, 300 ms por nivel.
- Cinco subslots de 54 ms: 39 ms activos y 15 ms guarda, con prefijo/sufijo de 15.
  DATA <=3 ms, espera ACK <=2, separación >=1; hasta tres intentos dentro del activo.
- Agregación de muestras congeladas por epoch, máximo 20; duplicados idénticos se
  unen, muestras distintas del mismo nodo se rechazan. Sin presupuesto, overflow;
  nunca prolongar slots ni atribuir muestra vieja a un epoch nuevo.
- Tres DATA sin ACK de aplicación cambian padre **al siguiente límite de epoch**;
  el callback ESP-NOW de enlace no equivale a ACK de aplicación ni a commit HTTP.
- Alertas `[1200,1420)`: cuatro rondas de 55 ms, escucha emisor 35 ms, escucha del
  nivel anterior `[R+5,R+40)` de 35 ms, cinco mini-TX de 1 ms por rama.
  `FIRE` en V-16 solo inyecta una muestra demo en cola; se transmite en su próximo
  mini-TX, **no interrumpe la cascada**. Los relays conservan los 12 bytes originales.
- Cache local de 20 entradas, retención 120 s, horizonte 6 s y hasta 3 envíos por
  entrada. Repetir bytes no reinicia horizonte ni contador. No hay TTL en radio.
- Silencio operativo `[1420,1500)` para sensores/UART, no para alargar radio.

El driver es asíncrono y CSMA puede retrasar una emisión. El callback mide si
terminó después del deadline y **bloquea nuevas transmisiones hasta reiniciar**;
no puede deshacer una colisión ya ocurrida. Los 1 ms y 6 Mbps son supuestos de
banco que se deben medir. No se promete entrega, exactly-once ni alerta en 220 ms.

### Deep Sleep y consumo real

`VITISCAN_ENABLE_DEEP_SLEEP=0` por defecto. Existe ruta Deep Sleep acotada de
250 ms para un nodo huérfano/sin sincronía y sin alerta pendiente, tras un margen
de adquisición despierto de 5 s; al despertar
vuelve a exigir sincronía. Gate RTC puede mantenerse. **No se duerme un repetidor
asociado entre ventanas**, porque boot, deriva RTC y reacquisición no están
validados. Tampoco se simula que apagar CPU permita recibir ESP-NOW dormido.

Las ventanas de 35 ms están filtradas por software; actualmente el receptor Wi-Fi
permanece encendido entre ellas. Por ello esta versión **no consigue ni promete**
el presupuesto de Deep Sleep segmentado del contrato para operación en campo.
Diseñar control temporal físico y medir wakeup/RX antes de habilitar ese ahorro.

Supuestos ilustrativos del contrato: TX 200 mA, RX 80 mA, activo 20 mA, sueño
0.01 mA; el DevKit puede consumir más por USB/regulador/LED. MQ-2 continuo ~900 mW
añade **21.6 Wh/día** antes de pérdidas: domina a una celda 2600 mAh ×3.7 V =9.62 Wh
(7.696 Wh al 80% útil). Con conversión 85%, del orden de **7 horas**, no días, con
calefactor continuo y sin contar todo el ESP32. Dos 18650 implican **1S2P protegido**,
mismo voltaje y doble capacidad; BMS/protección adecuada obligatorios. No es diseño
de baterías certificado ni autorización para conectar celdas sin protección.

## Gateway UART → HTTP

El Gateway recibe exclusivamente ventanas válidas, deduplica por nodo/epoch y
encola los bytes originales recibidos, hasta 16 tramas. UART se drena por chunks
sin bloquear, fuera de radio; el ACK de aplicación solo confirma recepción en el
Gateway, **no persistencia del backend**. Si la cola llena, no inventa entrega.

UTC se provisiona externamente con `UTC <Unix microsegundos>`, por UART; no ajusta
el reloj de TDMA ni sale por radio. Sin UTC válido, una recepción se imprime como
`quarantine`, no se fabrica timestamp. La sincronía UART de PC tiene retraso por
serial: es aproximación de banco, no sincronización UTC metrológica.

Envelope UART JSONL del perfil HTTP binario ya implementado:
`gateway_id`, `mode`, `cycle_id` UUID externo, `received_at` UTC de recepción y
`payload_hex`. Cada alerta nueva lleva su UUID dedicado. Sin referencia al instante
de origen no existe `latency_ms`: no se inventa cero ni se extrae de la cabecera.
Este envelope **no es el contrato HTTP `batches` congelado**, ni JSON por radio.

Backend y puente (con el mismo token de ingesta en ambos procesos):

```powershell
$env:GATEWAY_INGEST_TOKEN='<secreto-independiente>'
.\venv\Scripts\python.exe -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
# Otra consola, mismo token:
.\venv\Scripts\python.exe src/firmware-esp32/tools/serial_bridge.py --port COM3
```

El puente provisiona UTC tras arranque, valida con `binary_protocol.py` y publica
a `/api/v1/gateway/ingest`. Conserva metadatos en reintentos, usa Bearer desde
entorno, rechaza redirecciones y HTTP fuera de localhost. Sin `--port` acepta stdin
JSONL. Diagnósticos `#` se omiten. Ante fallo de ingesta se detiene y reporta
cuarentena; **no hay spool durable**: guardar UART externamente si se requiere
recuperación. No hay garantías de entrega tras corte de alimentación.

El backend actual es **simulation-only**: el puente rechaza `mode=real`; jamás
cambia el bit synthetic de muestras físicas para forzar su aceptación. Ingesta de
sensores reales necesita backend/almacenamiento real autorizado en otra fase.

## Pruebas

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_firmware_parity -v
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m unittest discover -s src/simulator -v
.\venv\Scripts\python.exe -O -m unittest discover -s tests -v
.\venv\Scripts\python.exe -O -m unittest discover -s src/simulator -v
```

No son solo regex: se compilan fixtures **C y C++ Xtensa**, se extraen secciones
del ELF generado y se comparan bytes exactos contra `struct` de Python: DATA,
ACK, BEACON, FIRE_ALERT, negativos y paquete de 246 B. `static_assert` también
evalúa temporización, RSSI, failover al límite de epoch, dedup, cache y agregación.
Sin toolchain, las pruebas compiladas se omiten explícitamente; instalarlo con
`python -m platformio pkg install -d src/firmware-esp32`. No se flashea ninguna placa
ni se confunde esta paridad binaria con validación RF, hardware o seguridad.

La auditoría añadió margen real de encolado: cada DATA reserva 6 ms de intento,
con deadline TX de 3 ms desde la entrada efectiva al driver, sin contar el tiempo
previo de codificación como si ya estuviera en el aire. Se corrigieron las dos
directivas #undef inválidas de OneWire 2.3.8 mediante un parche idempotente solo en
`.pio/libdeps`; no se silencian warnings ni se edita el entorno Python. Targets
compilan con `-Werror`. Gateway no incluye inicializadores de sensores ajenos.
