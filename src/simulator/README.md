# Simulador ESP-NOW — Viñedos Tarija

Python **3.11 o posterior**, solo biblioteca estándar. Desde la raíz del proyecto:

```powershell
python src/simulator/cli_demo.py
python -m unittest discover -s src/simulator -v
python -O -m unittest discover -s src/simulator -v
```

Si `python` resuelve al alias de Microsoft Store, utiliza el entorno ya instalado:

```powershell
.\venv\Scripts\python.exe src/simulator/cli_demo.py
.\venv\Scripts\python.exe -m unittest discover -s src/simulator -v
```

## Layout v2.0.0 y perfil de demostración

El simulador lee `.contracts/02_system_contract.json` con rutas relativas a sus propios archivos, sin depender del directorio de invocación. Rechaza otra versión. El contrato v1 original se conserva íntegro en `.contracts/archive/`.

- Cabecera `<BBBBBB>`: 6 bytes. BEACON=1, CASCADE_DATA=2, ACK=3, FIRE_ALERT=255.
- Lectura **`<BhHhBHBB>`**, 12 bytes: temperaturas signed int16, humedad de suelo uint16, gas uint16, batería uint8. El formato originalmente solicitado `<BhhHBBHB>` no representa los tamaños/signos acordados.
- `gas_smoke_ppm`: **0–1000 ppm sintéticos/normalizados**, por instrucción explícita de esta fase; no una medición física ni ppm de un compuesto identificado. `status_flags.synthetic` es obligatorio para este gas válido. Sin calibración, un dato real debe marcar gas inválido y valor cero. **Divergencia explícita:** el contrato congelado sigue en 0–500 y no se modifica ni en disco ni en memoria; valores >500 pertenecen solo al perfil demo y no son conformes a sus validaciones de ingesta. No hay marcador de perfil en radio: coordinarlo externamente. IDW y backend siguen pendientes.
- Longitud exacta `6 + 12 * reading_count`, sin padding ni campos ocultos; máximo 20 lecturas y 246 bytes. Validación de rangos, flags, IDs, destino, conteo, duplicados y longitud tanto al escribir como al leer. Los asserts verifican tamaños; la validación de entradas sigue activa con `python -O`.
- La fragmentación devuelve grupos independientes. Como solo hay 20 IDs válidos, la demo de 45 entradas incluye reenvíos (20+20+5), no 45 nodos. No hay índices de fragmento; el Gateway deduplica por nodo dentro del epoch externo. Conflictos de bytes para el mismo nodo/epoch se rechazan.

## Modelo de red

Topología sintética WGS84 tomada del contrato: Gateway y 20 nodos en cinco ramas de cuatro niveles, 22 m entre niveles de la misma rama. RSSI por pérdida logarítmica en distancia, determinista y no medido; candidatos siempre del nivel anterior. BEACON solo del Gateway; niveles superiores descubren padres por escucha de CASCADE_DATA de mantenimiento. Esos sondeos no se ingieren como telemetría.

El reloj virtual es común y los epochs son externos. No hay timestamps ni sincronización RF implementada. La tabla de pares MAC-ID está provisionada. La demo invoca ciclos consecutivos bajo demanda; el presupuesto de batería supone telemetría cada 900 s, no una cascada cada 1.5 s.

La demo verifica 20/20 lecturas nominales, apaga **V-01 (Nivel 1)**, observa tres intentos fallidos de V-06 y su conmutación al respaldo por RSSI al límite del epoch. El siguiente ciclo recupera 19/20 lecturas (solo falta V-01). Después inyecta **900 ppm sintéticos en V-16**, imprime los bytes reales de FIRE_ALERT y las ventanas receptoras de 35 ms para los cuatro saltos hasta Gateway.

TDMA de 4 a 1: 300 ms por nivel, 1200 ms total, sub-slots por ID/rama de 54 ms (39 activos y 15 de guarda), con 15 ms de guarda inicial y final. ACK de aplicación separado del callback de enlace. Tres intentos sin ACK cambian padre al **límite de epoch**, no durante un slot. Sin respaldo se declara huérfano; muestras perdidas no se convierten en observaciones cero ni pasan como nuevas al siguiente epoch. Pérdidas de DATA y ACK se pueden inyectar con los argumentos del constructor.

Superframe de 1500 ms: cascada `[0,1200)`, alertas `[1200,1420)`, silencio `[1420,1500)`. Cuatro rondas de 55 ms, escucha de 35 ms y cinco mini-TX de 1 ms por rama. Flooding broadcast orientado hacia adentro, cache de 120 s, horizonte local de 6 s y máximo tres transmisiones por entrada. Se conservan los 12 bytes del origen y se deduplica en el Gateway. El motor valida que no haya TX/RX simultáneos. Los límites de airtime son supuestos: no se emulan CSMA, fading, jitter RF ni drift. La detección sintética evalúa gas >=300 ppm o delta ambiente >=8 °C en <=60 s; el muestreo de seguridad previsto es cada 45 s, pero la demo inyecta la alarma directamente, sin esperar tiempo de pared.

## Energía

Modelo nominal conservador de reservas de escucha, TX/ACK, despertares y adquisición cada 45 s. Incluye ventana propia y de hijos cuando corresponde. Parámetros visibles en `simulation.battery_model`: 2600 mAh/celda, 3.7 V, fracción utilizable 80%, conversión 85%, corrientes y calentador ilustrativos.

Se muestran por separado **electrónica sola** y electrónica con **calentador MQ-2 continuo de 900 mW**. Sin calentador/calibración no se afirma detección válida. Dos celdas significan **1S2P protegido**, mismo voltaje y doble capacidad; no conectar celdas sin BMS/protecciones adecuadas. No incluye envejecimiento, autodescarga, regulador concreto ni operación sostenida bajo incendio. No extrapolar la autonomía electrónica a un nodo MQ-2 real.

Los datos quedan listos para consumir por un backend IDW; aquí no se implementan FastAPI, interpolación ni dashboard. No se transmite radio real ni se contacta ningún servicio.

**Prototipo no certificado para alertas de seguridad.**
