# VitiScan Tarija · Dashboard NOC / GIS

HTML, CSS y JavaScript sin Node, npm ni bundler para servir o usar la aplicación.
FastAPI sirve `/`, `/styles.css` y `/app.js`; la API mantiene sus rutas anteriores.
Leaflet **1.9.4** y Leaflet.heat **0.2.0** se cargan desde CDN con versiones y SRI
fijados. La cartografía de OpenStreetMap y las librerías CDN requieren Internet.

## Arranque local para el jurado

Desde PowerShell en `D:\desarrollo`:

```powershell
.\venv\Scripts\python.exe -m src.backend.run_demo
```

Inicializa el historial sintético sin borrar datos, ejecuta una cascada nominal,
levanta **Uvicorn solo en `127.0.0.1:8000`** y abre el navegador automáticamente.
`--no-browser` evita abrirlo; `--print-command` imprime los comandos sin arrancar.
Ctrl+C detiene el servidor. Un único worker, sin confianza en cabeceras de proxy.

Equivalente manual (no inicializa muestras por sí solo):

```powershell
$env:APP_MODE='simulation'
$env:SIM_ACTIONS_ENABLED='true'
$env:DASHBOARD_LOCAL_DEMO='true'
.\venv\Scripts\python.exe -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

En otra consola:

```powershell
Start-Process 'http://127.0.0.1:8000'
```

El perfil local es **opt-in**. La raíz entrega una cookie aleatoria de sesión
`HttpOnly`, `SameSite=Strict`, limitada a `/api/v1/sim`, solo a un cliente y Host
loopback. Cada POST con cookie debe tener `Origin` exactamente igual al servidor.
La sesión no expone tokens de Gateway/operador en HTML, JS, URL ni consola; tampoco
autoriza ingesta. No activar este perfil detrás de proxy ni para exposición LAN.
Solo usar este almacenamiento de simulación. El contrato congelado no se modifica.

Con el arranque normal, las acciones siguen deshabilitadas por defecto. Si se
habilitan sin perfil local, el formulario acepta `OPERATOR_TOKEN`: se conserva
solo en memoria hasta recargar/salir, sin `localStorage`, `sessionStorage` ni URL.
`GATEWAY_INGEST_TOKEN` sigue siendo independiente y necesario para ingesta externa.
Al compartir origen UI/API no es necesario ampliar CORS. Revisar
[`../backend/README.md`](../backend/README.md) para el perfil Bearer.

## Qué se visualiza

- Gateway N0 y 20 nodos en 5 ramas, centrados en −21.6485, −64.6342. Anillos de
  22, 44, 66 y 88 m. Posiciones sintéticas, no un relevamiento real del viñedo.
- Verde: normal; ámbar: failover; gris: caído/sin confirmar; rojo: alerta activa.
  Las polilíneas siguen `operational_parent_id`, incluido Gateway ID **0**. No se
  inventa padre activo si es desconocido. Un enlace semilla se distingue como no
  confirmado; tras failover el primario fallido se muestra como referencia roja
  tenue **inactiva**, mientras V-06 → V-02 es el respaldo activo.
- Malla IDW p=2: humedad de suelo, temperatura ambiente/suelo, gas/humo sintético
  y riesgo térmico demo. `points` usa `[lat,lon,intensidad]`; `values` conserva las
  unidades para consultar una celda con el cursor. Se usa **Canvas raster IDW**,
  no suma de densidades: Leaflet.heat sobre una malla densa podría saturar colores
  y falsear magnitudes. El suavizado del raster es solo visual; los cálculos
  siguen en backend. Una celda sin fuentes no se dibuja como una medición cero.
- Tabla y detalle por nodo: nivel, estado, batería, RSSI, padre, humedad y
  temperaturas, respetando bits de invalidez. Valores ausentes muestran `—`.
- Visor de bytes **realmente devueltos por `/sim/trigger`**: selección de tramas,
  6 bytes de cabecera azules, bloques de 12 bytes por nodo verdes. No se añaden
  timestamps ni se muestran paquetes prefabricados antes de una simulación.

Si falla la cartografía, la topología local sigue disponible. Si falla el CDN de
Leaflet, la interfaz muestra un aviso y conserva tabla, controles y visor HEX;
no finge que existe un mapa interactivo sin la librería.

## Cuatro escenarios

### Maqueta Física / Gemelo Digital

Panel integrado debajo del mapa GIS, sin librerías adicionales. El tablero SVG
mantiene las posiciones locales de los 20 nodos y las distancias relativas:
Gateway N0 en el centro, hileras vitícolas en N1–N3, perímetro forestal N4,
sensor V-16 y poste repetidor V-01 con interruptor representado. Referencia
**1:200**: 22 m reales equivalen a 11 cm en una maqueta; el tamaño en pantalla
no es una regla física. Selección por clic, Enter o espacio, y detalle compartido
con tabla/mapa. LEDs animados verde/ámbar/rojo; gris es desconocido y apagado es
sin energía. Se respeta movimiento reducido y el panel se adapta a móvil.

- **Regar Suelo en Maqueta**: elegir rama 1–5; aumenta hasta 20 puntos porcentuales
  por pulsación (máximo 100%) en sus nodos válidos de N1–N3, nunca en el bosque.
  Muestra humedad **recibida** y humedad **local** separadas, ilumina el sector y
  selecciona la capa de humedad. El IDW local usa p=2 en metros, coincidencia
  exacta a 1 mm y 289 celdas a 11 m; mantiene el raster Canvas y consulta de celda.
  Excluye canales inválidos, nodos apagados/desconocidos, lecturas >1 h y fechas
  futuras >5 s. Sin fuentes no inventa un cero.
- El riego es una **previsualización exclusiva del navegador**, marcada
  `RIEGO LOCAL`. No envía ingesta, no crea paquetes HEX, no cambia SQLite ni los
  endpoints IDW del backend. Se conserva ante polling y cambios de capa mientras
  la página permanezca abierta; **Limpiar riego local**, restaurar o recargar
  retiran los valores locales. No es un actuador de riego.
- **Cortar Switch Poste V-01** reutiliza `failover`: solo tras confirmación y
  actualización se apaga V-01, se enciende ámbar y se dibuja V-06 → V-02.
- **Acercar Humo a Sensor MQ-2 (V-16)** reutiliza `fire`: rojo únicamente tras
  `0xFF`/alerta confirmada, capa de gas actualizada y escucha RF virtual de 35 ms.
  La animación no constituye una medición de tiempo RF.

Se mantienen las mismas sesiones/tokens, bloqueo de acciones e idempotencia de
los controles originales. Los escenarios del servidor siguen siendo
**independientes**: humo no conserva artificialmente un switch cortado si el
backend comunica una topología nominal. Si se pierde conexión se conserva el
último estado con aviso, no se finge confirmación. El panel y sus controles
funcionan incluso si Leaflet/CDN no carga; el GIS muestra su aviso habitual.

Las pruebas añaden validación del riego, saturación, exclusión de fuentes,
interpolación exacta, LEDs y escala; Chrome verifica controles físicos, polling
sin perder la previsualización, backend/HEX intactos tras riego, teclado, movimiento
reducido y móvil. El contrato congelado conserva su SHA-256.

### Escenarios confirmados del backend

Los botones envían JSON a `POST /api/v1/sim/trigger` con `action`, UUID de
`idempotency_key` y `mode=simulation`. No hay JSON por radio.

1. `cascade`: 20/20 y tramas TDMA N4 → N1 → Gateway.
2. `failover`: 20 → 16 → 19 lecturas; V-01 cae, V-06 cambia de V-01 a V-02.
3. `fire`: V-16 origina 450 ppm sintéticos y una trama `0xFF`; banner pulsante,
   foco rojo, selección automática de la capa ppm y bytes de alerta confirmados.
4. `restore`: nuevo ciclo nominal 20/20 y cierre **explícito de eventos demo**;
   no borra historial ni equivale a extinguir un incendio real.

Las acciones son escenarios independientes, no un estado RF físico persistente.
Ejecutar un ciclo nominal por sí solo no descarta una alerta activa: para cerrar
la demostración se usa Restaurar. Claves nuevas por acción; ante pérdida de
confirmación de red se retiene la identidad para reintentar sin duplicar a ciegas.
Los controles se bloquean mientras hay una acción en curso; no se comunica éxito
ni se enciende una alerta como si fuera recibida antes de confirmar el backend.

### Actualización y tiempos

`GET /api/v1/dashboard/config` expone solo Gateway, temporización, habilitación y
modo de autenticación, sin secretos. Alertas por `GET /api/v1/alerts/fire` cada
**500 ms**, sin solicitudes superpuestas. Red y malla se consultan cada 2 s, y de
inmediato después de cada acción. Respuestas anteriores no pisan un escenario
nuevo ni una capa recién seleccionada; ante errores se conserva el último estado
con un aviso, no se declara normalidad ni incendio extinguido por falta de conexión.

Objetivo de demostración: aviso de interfaz **<1 s en localhost**; la respuesta
confirmada del botón se representa sin esperar al siguiente polling. Se mide y
muestra el tiempo web, separado de la **latencia RF virtual (~1401 ms)**. Polling,
red, carga o pestañas en segundo plano impiden garantizar el plazo; no es una
promesa de latencia de hardware ni se reduce el superframe de **1500 ms** o las
ventanas de **35 ms** para fingirla. Animaciones respetan `prefers-reduced-motion`.

La recepción UTC del puente se marca al reproducir cada entrega en el Gateway
simulado. La fase/latencia conserva el reloj virtual externo. No se resta toda
la duración virtual a UTC: ejecutar escenarios sin espera no debe hacer que una
alerta nueva quede detrás de una muestra anterior en el historial.

Auditoría: respuestas 5xx/409 o confirmaciones inválidas conservan UUID al
reintentar; no se interpreta un resultado incompleto como éxito. El visor HEX
valida también IDs/niveles/rangos/flags. Al cambiar capa se retira la malla previa
para no presentar valores viejos con unidades nuevas. `/index.html` inicia la
misma sesión segura que `/`; la tabla mantiene foco de teclado al refrescar.

## Verificación

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_frontend_integration -v
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m unittest discover -s src/simulator -v
```

Pruebas con bases temporales, sin modificar la base del jurado. La comprobación de
funciones JS se omite automáticamente si Node no está instalado. Verificación
visual adicional **opcional**, solo en desarrollo con Chrome y Node disponibles:

```powershell
node tests/frontend_browser_smoke.cjs
```

Arranca Uvicorn y Chrome headless en puertos temporales; comprueba los cuatro
botones, polling externo, cinco capas, enlace V-06 → V-02, banner <1 s en esa
ejecución, bytes reales y ausencia de overflow móvil. Capturas se guardan en
`%LOCALAPPDATA%\Temp\opencode\vitiscan-visual-*`; elimina sus procesos y base
temporal al finalizar. Chrome puede indicarse con `CHROME_PATH`.

**Prototipo no certificado.** Gas 0–1000 solo en el perfil demo; contrato v2
congelado mantiene 0–500. Umbral 300 e incendio 450 son exclusivamente sintéticos.
