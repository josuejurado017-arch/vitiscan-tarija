/* Verificacion visual OPCIONAL: node tests/frontend_browser_smoke.cjs.
   Requiere Chrome + Node con WebSocket nativo; no son dependencias del dashboard. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {setTimeout: delay} = require('node:timers/promises');

const root = path.resolve(__dirname, '..');
const approved = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'opencode');

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function waitFor(operation, message, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try { const value = await operation(); if (value) return value; } catch (_) { /* arranque */ }
    await delay(35);
  }
  throw new Error('Timeout: ' + message);
}

async function main() {
  await fs.mkdir(approved, {recursive: true});
  const temporary = await fs.mkdtemp(path.join(approved, 'vitiscan-browser-'));
  const artifacts = await fs.mkdtemp(path.join(approved, 'vitiscan-visual-'));
  const port = await freePort(); const debugPort = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const chromePath = process.env.CHROME_PATH || path.join(process.env.PROGRAMFILES, 'Google/Chrome/Application/chrome.exe');
  const server = spawn(path.join(root, 'venv/Scripts/python.exe'), ['-m', 'uvicorn', 'src.backend.main:app',
    '--host', '127.0.0.1', '--port', String(port), '--no-proxy-headers'], {cwd: root,
    env: {...process.env, APP_MODE: 'simulation', SIM_ACTIONS_ENABLED: 'true', DASHBOARD_LOCAL_DEMO: 'true',
      OPERATOR_TOKEN: 'isolated-browser-test-operator',
      VITISCAN_DB_PATH: path.join(temporary, 'isolated.db')}, stdio: ['ignore', 'pipe', 'pipe']});
  let serverLog = ''; server.stderr.on('data', chunk => { serverLog += chunk; });
  let browser; let socket; const errors = []; let browserLog = '';
  try {
    await waitFor(async () => (await fetch(origin + '/api/v1/dashboard/config')).ok, 'Uvicorn local');
    browser = spawn(chromePath, ['--headless=new', '--no-first-run', '--no-default-browser-check',
      '--disable-extensions', '--disable-background-networking', `--user-data-dir=${path.join(temporary, 'chrome')}`,
      `--remote-debugging-port=${debugPort}`, 'about:blank'], {stdio: ['ignore', 'pipe', 'pipe']});
    browser.stderr.on('data', chunk => { browserLog += chunk; });
    const targets = await waitFor(async () => {
      const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
      return targets.find(target => target.type === 'page');
    }, 'Chrome CDP');
    socket = new WebSocket(targets.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let nextId = 0; const pending = new Map();
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const operation = pending.get(message.id); pending.delete(message.id);
        if (message.error) operation.reject(new Error(JSON.stringify(message.error)));
        else operation.resolve(message.result);
      } else if (message.method === 'Runtime.exceptionThrown') {
        errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
      } else if (message.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(message.params.type)) {
        errors.push(message.params.args.map(value => value.value || value.description || '').join(' '));
      } else if (message.method === 'Log.entryAdded' && ['error', 'warning'].includes(message.params.entry.level)) {
        errors.push(message.params.entry.text);
      }
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++nextId; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));
    });
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || 'JS error');
      return result.result.value;
    };
    await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
    await send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
    await send('Page.navigate', {url: origin});
    await waitFor(() => evaluate("document.querySelector('[data-action=cascade]')?.disabled === false && document.querySelectorAll('#node-table tr').length === 20"), 'dashboard listo');
    assert.equal(await evaluate('typeof window.L?.map'), 'function', 'Leaflet debe cargar desde CDN');
    const action = async (name, expectedText) => {
      await evaluate(`document.querySelector('[data-action=${name}]').click()`);
      await waitFor(() => evaluate(`!document.querySelector('[data-action=${name}]').disabled && document.getElementById('action-status').textContent.includes(${JSON.stringify(expectedText)})`), name);
    };
    // Una respuesta 503 tras commit no debe generar otra identidad en el reintento.
    await evaluate(`window.__fetchOriginal=window.fetch; window.__retryKeys=[]; window.__retryRuns=[];
      window.fetch=async (input, options={}) => {
        const response=await window.__fetchOriginal(input, options);
        if (String(input)==='/api/v1/sim/trigger') {
          window.__retryKeys.push(JSON.parse(options.body).idempotency_key);
          if(response.ok) window.__retryRuns.push((await response.clone().json()).run_id);
          if(window.__retryKeys.length===1) return new Response(JSON.stringify({detail:'Confirmacion perdida despues de commit'}), {status:503,headers:{'Content-Type':'application/json'}});
        }
        return response;
      }; document.querySelector('[data-action=cascade]').click();`);
    await waitFor(() => evaluate("!document.querySelector('[data-action=cascade]').disabled && document.getElementById('action-status').textContent.includes('Estado incierto')"), '503 controlado sin exito supuesto');
    await action('cascade', '20/20');
    assert.equal(await evaluate('window.__retryKeys[0]===window.__retryKeys[1] && window.__retryRuns[0]===window.__retryRuns[1]'), true);
    await evaluate('window.fetch=window.__fetchOriginal');
    assert.equal(await evaluate("document.getElementById('active-count').textContent"), '20/20');
    assert.equal(await evaluate("document.querySelectorAll('#hex-viewer .header-byte').length"), 6);
    assert.equal(await evaluate("document.querySelectorAll('#hex-viewer .hex-byte:not(.header-byte)').length"), 48);
    await action('failover', '19/20');
    assert.equal(await evaluate("document.getElementById('active-count').textContent"), '19/20');
    assert.equal(await evaluate("Boolean(document.querySelector('[data-child=\"6\"][data-parent=\"2\"][data-active=\"true\"]'))"), true);
    await evaluate("window.__fireClick = performance.now(); document.querySelector('[data-action=fire]').click()");
    await waitFor(() => evaluate("!document.getElementById('fire-banner').hidden"), 'banner rojo');
    const visibleMs = await evaluate('Math.round(performance.now() - window.__fireClick)');
    assert.ok(visibleMs < 1000, `Aviso web <1s en esta prueba local: ${visibleMs} ms`);
    await waitFor(() => evaluate("!document.querySelector('[data-action=fire]').disabled"), 'incendio finalizado');
    assert.equal(await evaluate("Boolean(document.querySelector('.node-fire[data-node-id=\"16\"]'))"), true);
    assert.equal(await evaluate("document.getElementById('heat-layer').value"), 'gas_smoke_ppm');
    assert.equal(await evaluate("document.querySelectorAll('#hex-viewer .hex-byte').length"), 18);
    assert.ok(await evaluate("document.getElementById('node-detail').textContent.includes('450 ppm')"), 'La telemetria mas reciente refleja el incendio');
    const screenshot = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
    await fs.writeFile(path.join(artifacts, 'desktop-fire.png'), Buffer.from(screenshot.data, 'base64'));
    await action('restore', '20/20');
    assert.equal(await evaluate("document.getElementById('fire-banner').hidden"), true);
    assert.equal(await evaluate("Boolean(document.querySelector('[data-child=\"6\"][data-parent=\"1\"][data-active=\"true\"]'))"), true);
    // Evento externo al boton: verificar que polling realmente enciende la alarma.
    const externalStart = Date.now();
    const external = await fetch(origin + '/api/v1/sim/trigger', {method: 'POST',
      headers: {'Content-Type': 'application/json', Authorization: 'Bearer isolated-browser-test-operator'},
      body: JSON.stringify({action: 'fire', idempotency_key: crypto.randomUUID()})});
    assert.equal(external.status, 200);
    await waitFor(() => evaluate("!document.getElementById('fire-banner').hidden"), 'polling de alerta externa');
    const externalMs = Date.now() - externalStart;
    assert.ok(externalMs < 1000, `Polling externo <1s en esta prueba: ${externalMs} ms`);
    await action('restore', '20/20');
    // Verificar cambio de capas contra los endpoints reales.
    for (const [layer, label] of [['amb_temp', 'Temperatura ambiente'], ['soil_temp', 'Temperatura de suelo'],
      ['thermal_risk', 'Riesgo térmico'], ['soil_moisture', 'Humedad de suelo']]) {
      await evaluate(`document.getElementById('heat-layer').value=${JSON.stringify(layer)}; document.getElementById('heat-layer').dispatchEvent(new Event('change'))`);
      await waitFor(() => evaluate(`document.getElementById('heat-unit').textContent.includes(${JSON.stringify(label)}) && document.getElementById('source-count').textContent.includes('20/20')`), layer);
    }
    await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await delay(300);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true, 'Sin overflow horizontal movil');
    const mobile = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
    await fs.writeFile(path.join(artifacts, 'mobile-restored.png'), Buffer.from(mobile.data, 'base64'));
    assert.deepEqual(errors, []);
    console.log(`BROWSER OK: 20/20 -> 19/20 (V-06 -> V-02) -> 0xFF V-16 -> restaurar 20/20.`);
    console.log(`Banner web confirmado en ${visibleMs} ms. Latencia RF virtual se conserva separada.`);
    console.log(`Evento externo detectado por polling en ${externalMs} ms; cinco capas verificadas.`);
    console.log(`Capturas: ${artifacts}`);
    await send('Browser.close').catch(() => {});
  } catch (error) {
    console.error('Errores JS:', errors);
    console.error(serverLog.slice(-2000)); console.error(browserLog.slice(-2000));
    throw error;
  } finally {
    socket?.close(); browser?.kill(); server.kill();
    await delay(800);
    await fs.rm(temporary, {recursive: true, force: true, maxRetries: 10, retryDelay: 200}).catch(() => {});
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
