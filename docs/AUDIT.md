# Auditoría integral · VitiScan Tarija

Alcance verificable: las cuatro fases implementadas en `src/`, su documentación,
datos SQLite y suite Python/C/C++/navegador. No se realizaron flasheos, ensayos RF,
calibración MQ-2 ni accionamiento físico. Aprobar todas las pruebas no significa
cobertura total de código, seguridad certificada ni preparación para producción.

## Integridad y reglas fijadas

Contrato activo `.contracts/02_system_contract.json`, versión 2.0.0, sin cambios:

```text
B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356
```

También se verifica el archivo v1 archivado. Se mantienen cabecera 6 B y lectura
12 B little-endian, 246 B máximo, códigos A5/01/02/03/FF, ADC1 GPIO34/35, 20 nodos
y Gateway, separación radial 22 m, superframe 1500 ms y escuchas 35 ms fuera de
cascada. Epoch, UTC, latencia, RSSI y sincronía no se esconden en la radio.

## Hallazgos corregidos y evidencia

| Módulo | Hallazgo / corrección | Evidencia |
|---|---|---|
| Protocolo Python | Constante de límite declaraba 250 aunque el perfil solo usa 246; ahora cota explícita 246 | Tamaños, fragmentación 20/21/45 entradas, comparación con bytes C/C++ |
| Simulador | IDs booleanos/fraccionarios podían tratarse como nodos, y alertas idénticas permanecían deduplicadas para siempre en Gateway | Regresiones IDs y nueva alerta después de 120 s |
| Simulador | Traza no contrastaba cabecera con evento ni detectaba emisiones simultáneas de dispositivos distintos en el canal | Validador de trama/evento, subslots, guards y half-duplex |
| SQLite / alertas | Un DATA crítico anterior podía impedir mostrar motivo 0xFF/latencia; retransmisiones fuera de orden creaban eventos duplicados | Upgrade de evento radio, dedup temporal sin retroceder last_seen |
| SQLite / estado | Alertas cerradas recientes podían preceder activas; metadatos sin muestras quedaban online indefinidamente | Orden activas primero y expiración de evidencia/RSSI/padres |
| API | JSON ambiguo, UTF-16 o excesivamente anidado; timestamps Unix numéricos aceptados como si fueran RFC3339 | 400/422 sin persistencia; profundidad limitada a 64 |
| IDW | Entrada pública no rechazaba valores/coordenadas no finitos o inválidos; `d**2` podía desbordar | Exclusión de fuentes incorrectas, pesos normalizados equivalentes p=2 y coincidencia exacta |
| Dashboard | 503 tras commit descartaba UUID y permitía duplicar una acción; index.html no iniciaba cookie local | Chrome simula confirmación perdida y comprueba misma clave/run_id; prueba de index.html |
| Dashboard | Cambio de capa podía consultar valores anteriores con unidades nuevas; visor validaba solo longitud/magic | Limpieza al cambiar capa, validación semántica de flags/rangos/IDs y paquetes reales |
| Dashboard | Falta de favicon causaba 404 de consola; regeneración de tabla podía perder foco | Icono embebido, conservación de foco y pruebas de consola/móvil |
| Firmware | DATA se pasaba al driver con deadline igual a su presupuesto: cualquier overhead lo rechazaba | Separación reserva 6 ms / airtime 3 ms, timestamp real de encolado, static_assert de plan TX |
| Firmware | Caducidad de observación de 60 s expulsaba al padre antes de una telemetría a 900 s | Asociación retenida hasta tres fallos; frescura exigida al elegir reemplazo |
| Firmware | Gateway compilaba inicializadores de sensores que no necesita | Target Gateway limita sus fuentes a radio/coordinación |
| Dependencias | TestClient advertía por httpx antiguo; OneWire 2.3.8 tenía dos #undef defectuosos | httpx2 declarado/fijado; parche idempotente en copia .pio, compilación -Werror sin silenciamiento |
| Repositorio | README raíz vacío de instrucciones y memoria desactualizada; venv ya versionado | Documentación sincronizada, reglas de ignore y retirada autorizada de 1.428 archivos solo del índice |

Se conserva el entorno en disco. No se hizo commit ni se retiraron otros cambios
del usuario. El firmware no versionado encontrado al iniciar se conservó y auditó.
`.gitattributes` fija LF en fuentes para eliminar advertencias de conversión en
Windows; `.contracts/**` queda excluido de normalización para conservar sus bytes.

## Resultados reproducibles

| Grupo | Estándar | `-O` |
|---|---:|---:|
| Simulador | 24/24 | 24/24 |
| Backend / IDW / SQLite | 39/39 | 39/39 |
| Frontend integración / lógica JS | 20/20 | 20/20 |
| Firmware / C/C++ ELF / UART-HTTP | 20/20 | 20/20 |
| **Total** | **103/103** | **103/103** |

Sin warnings ni omisiones en la suite. `tools/run_tests.py` trata warnings como
errores y falla si se omite un grupo por faltar toolchain/Node de QA. Se comprobó
además `pip check`, compilación de ambos targets con `-Werror`, seed no destructivo
y ejecución Chrome headless en base temporal, con errores/warnings de consola
capturados. El navegador verifica cinco capas, cuatro botones, V-06 → V-02,
restauración, polling de un evento externo y reintento tras 503 conservando UUID.

En la ejecución local de navegador, banner confirmado en **379 ms** y alerta
externa detectada en **457 ms**. No son garantías: carga, red y pestañas en segundo
plano modifican tiempos. La RF virtual conserva ~1401 ms y se muestra por separado.

El seed confirmó 96 épocas/1920 lecturas históricas objetivo: en esta ejecución
140 nuevas, 1780 ya existentes, y ciclo en vivo 20/20 en cinco tramas. La base
puede contener épocas/corridas anteriores; no se elimina historial para cuadrar
un contador. SQLite mantiene WAL, claves foráneas y conexiones cerradas por operación.

```powershell
.\venv\Scripts\python.exe src/backend/seed_tarija.py
.\venv\Scripts\python.exe tools/run_tests.py
.\venv\Scripts\python.exe -O tools/run_tests.py
.\venv\Scripts\python.exe -m platformio run -d src/firmware-esp32
node tests/frontend_browser_smoke.cjs
```

## Diferencias explícitas / deuda no certificada

No modificar un documento congelado para aparentar conformidad:

1. **Perfil demo frente a contrato:** las fases posteriores solicitaron gas
   0..1000 sintético, HTTP binario/HEX, `/nodes/status`, `/sim/trigger`, cookie
   local y polling 500 ms. El contrato mantiene gas 0..500, ingesta JSON `batches`,
   `/actions/*`, Bearer y polling 1000 ms. El binario comparte layout, no implica
   conformidad semántica de valores >500 ni API contractual completa. Implementar
   esa API/modo real o versionar el perfil requiere una fase/revisión explícita.
2. **Sincronía física:** BEACON no contiene reloj. GPIO32/GPIO39 y comandos UART
   son propuesta de banco, no contrato de control aprobado. TX de aplicación
   sigue bloqueado por defecto. Faltan ensayos de fase, deriva, CSMA y callbacks.
3. **Energía/sensores:** MQ-2 físico queda inválido incluso tras warmup, sin curva
   inventada. Deep Sleep de repetidores y duty-cycle real no están validados;
   RX sigue encendido. No prometer autonomía de simulación en una placa.
4. **Identidad/fiabilidad:** sin secuencia/TTL/versión en radio no se puede probar
   exactly-once, ACK inequívoco o anti-replay físico. Sin CRC propio, cambios de
   bytes que sigan siendo válidos no son detectables por validación estructural.
5. **Operación del prototipo:** simulaciones de varias tramas no son una sola
   transacción; un corte puede dejar corrida parcial. Un claim interrumpido no se
   vuelve a ejecutar a ciegas. UART no tiene spool durable y UTC serial es de banco.
6. **Pila previa:** .NET/Angular/IA/PostGIS/Compose no forma el pipeline auditado
   ESP-NOW. Tiene otro despliegue y ocupa puertos que pueden colisionar (8000).
   Requiere auditoría/servicios/suite propios antes de integrarse; no se inició
   Docker ni se modificaron bases Postgres o actuadores.

Son límites funcionales/arquitectónicos registrados, no warnings ocultos ni
pruebas omitidas. La demo está comprobada; el despliegue físico no está aprobado.
