/* Dashboard sin bundler. Solo usa respuestas confirmadas; nunca fabrica tramas. */
(() => {
  'use strict';

  const LAYERS = {
    soil_moisture: {title: 'Humedad de suelo · %', low: '0 %', high: '100 %', unit: '%',
      gradient: {0: '#172c73', 0.5: '#2899d5', 1: '#44d4c3'}},
    amb_temp: {title: 'Temperatura ambiente · °C', low: '−10 °C', high: '60 °C', unit: '°C',
      gradient: {0: '#2864c4', 0.5: '#ffe391', 1: '#ff536b'}},
    soil_temp: {title: 'Temperatura de suelo · °C', low: '−10 °C', high: '60 °C', unit: '°C',
      gradient: {0: '#2864c4', 0.5: '#ffe391', 1: '#ff536b'}},
    gas_smoke_ppm: {title: 'Gas / humo · ppm sintéticos', low: '0 ppm', high: '1000 ppm', unit: 'ppm demo',
      gradient: {0: '#283850', 0.3: '#f3b257', 0.65: '#fa704f', 1: '#ff365d'}},
    thermal_risk: {title: 'Riesgo térmico · índice demo', low: '0', high: '1 · no probabilidad', unit: 'índice demo',
      gradient: {0: '#315867', 0.5: '#ffbd62', 1: '#ff365d'}},
  };
  const COLORS = {normal: '#4adea3', backup: '#ffbd62', offline: '#8392a5', unknown: '#8392a5', fire: '#ff6174'};
  const STATUS = {normal: 'Normal', backup: 'Failover', offline: 'Caído', unknown: 'Sin confirmar', fire: 'Incendio'};
  const MESSAGE_TYPES = {1: 'BEACON', 2: 'CASCADE_DATA', 3: 'ACK', 255: 'FIRE_ALERT'};
  const levelFor = id => id === 0 ? 0 : id >= 1 && id <= 20 ? Math.floor((id - 1) / 5) + 1 : -1;
  const uncertainFailure = error => !Number.isInteger(error.status) || error.status >= 500 || error.status === 409;

  function nodeLabel(id) { return id === 0 ? 'GW-00' : `V-${String(id).padStart(2, '0')}`; }

  function parentFor(node) {
    if (['offline', 'orphan', 'stale', 'unknown'].includes(node.state)) return null;
    // Gateway ID=0 es valido. Un padre null no se convierte en un enlace activo.
    if (node.operational_parent_id !== null && node.operational_parent_id !== undefined) {
      return node.operational_parent_id;
    }
    return node.state === 'seed' ? (node.primary_parent ?? null) : null;
  }

  function nodeVisualState(node, fireNodes = new Set()) {
    if (fireNodes.has(node.node_id)) return 'fire';
    if (node.state === 'offline') return 'offline';
    if (node.state !== 'online' && node.state !== 'sleeping') return 'unknown';
    return node.failover || node.using_backup_parent ? 'backup' : 'normal';
  }

  function parseFrame(hex) {
    if (typeof hex !== 'string') throw new Error('Trama HEX ausente.');
    const compact = hex.replace(/\s/g, '');
    if (!compact || compact.length % 2 || !/^[0-9a-f]+$/i.test(compact)) throw new Error('HEX inválido.');
    const bytes = Uint8Array.from(compact.match(/../g), value => Number.parseInt(value, 16));
    if (bytes.length < 6 || bytes.length > 246) throw new Error('Tamaño de trama inválido.');
    const [magic, type, level, sender, parent, count] = bytes;
    if (magic !== 0xa5 || !MESSAGE_TYPES[type] || count > 20 || bytes.length !== 6 + count * 12) {
      throw new Error('Cabecera o longitud incompatible con 6 B + 12 B × n.');
    }
    const headerValid = levelFor(sender) === level && (type === 1
      ? sender === 0 && parent === 255 && count === 0
      : type === 2 ? sender !== 0 && count >= 1 && levelFor(parent) === level - 1
        : type === 3 ? count === 0 && levelFor(parent) === level + 1
          : sender !== 0 && parent === 255 && count === 1);
    if (!headerValid) throw new Error('IDs, niveles o conteo incompatibles con el protocolo.');
    const view = new DataView(bytes.buffer);
    const readings = [];
    for (let index = 0; index < count; index++) {
      const offset = 6 + index * 12;
      readings.push({node_id: view.getUint8(offset), soil_temp_x10: view.getInt16(offset + 1, true),
        soil_moisture: view.getUint16(offset + 3, true), amb_temp_x10: view.getInt16(offset + 5, true),
        amb_humidity: view.getUint8(offset + 7), gas_smoke_ppm: view.getUint16(offset + 8, true),
        battery_pct: view.getUint8(offset + 10), status_flags: view.getUint8(offset + 11)});
    }
    const seen = new Set();
    for (const reading of readings) {
      const channels = [reading.soil_temp_x10, reading.soil_moisture, reading.amb_temp_x10,
        reading.amb_humidity, reading.gas_smoke_ppm, reading.battery_pct];
      const limits = [[-550, 1250], [0, 10000], [-400, 800], [0, 100], [0, 1000], [0, 100]];
      if (levelFor(reading.node_id) < 1 || seen.has(reading.node_id)
          || channels.some((value, bit) => value < limits[bit][0] || value > limits[bit][1]
            || Boolean(reading.status_flags & (1 << bit)) && value !== 0)
          || !(reading.status_flags & 128) && !(reading.status_flags & 16)) {
        throw new Error('Lectura fuera de rango, duplicada o con flags inválidos.');
      }
      seen.add(reading.node_id);
    }
    if (type === 255 && !(readings[0].status_flags & 64)) throw new Error('FIRE_ALERT sin bit fire_triggered.');
    return {bytes, magic, type, level, sender, parent, count, readings};
  }

  // El riego es una previsualizacion LOCAL, nunca una lectura ni una trama RF.
  function moistureSource(node, now = Date.now()) {
    const received = Date.parse(node.last_seen_at);
    if (!Number.isInteger(node.node_id) || node.node_id < 1 || node.node_id > 20
        || !['online', 'sleeping'].includes(node.state)
        || !Number.isInteger(node.status_flags) || node.status_flags < 0 || node.status_flags > 255
        || node.status_flags & 2 || !Number.isInteger(node.soil_moisture)
        || node.soil_moisture < 0 || node.soil_moisture > 10000
        || !Number.isFinite(received) || now - received > 3600000 || received - now > 5000
        || !Number.isFinite(node.lat) || !Number.isFinite(node.lon)
        || Math.abs(node.lat) > 90 || Math.abs(node.lon) > 180) return null;
    return node.soil_moisture / 100;
  }

  function irrigateSector(nodes, previous, branch, now = Date.now()) {
    if (!Number.isInteger(branch) || branch < 1 || branch > 5) throw new Error('Sector de riego inválido.');
    const result = new Map(previous);
    for (const node of nodes) {
      const baseline = moistureSource(node, now);
      if (node.branch !== branch || node.level < 1 || node.level > 3 || baseline === null) continue;
      const current = result.get(node.node_id) ?? baseline;
      if (!Number.isFinite(current) || current < 0 || current > 100) throw new Error('Humedad local inválida.');
      result.set(node.node_id, Math.min(100, current + 20));
    }
    return result;
  }

  function irrigationHeatmap(nodes, irrigation, gateway, now = Date.now()) {
    if (!Number.isFinite(gateway.lat) || !Number.isFinite(gateway.lon)) throw new Error('Gateway sin coordenadas.');
    const radius = 6378137; const radians = Math.PI / 180;
    const cos = Math.cos(gateway.lat * radians);
    const local = (lat, lon) => [(lon - gateway.lon) * radians * radius * cos, (lat - gateway.lat) * radians * radius];
    const sources = []; const seen = new Set();
    for (const node of nodes) {
      const baseline = moistureSource(node, now);
      if (baseline === null || seen.has(node.node_id)) continue;
      const value = irrigation.get(node.node_id) ?? baseline;
      if (!Number.isFinite(value) || value < 0 || value > 100) throw new Error('Humedad local fuera de rango.');
      const [east, north] = local(node.lat, node.lon);
      sources.push([east, north, value]); seen.add(node.node_id);
    }
    const points = []; const values = [];
    if (sources.length) for (let north = -88; north <= 88; north += 11) {
      for (let east = -88; east <= 88; east += 11) {
        const distances = sources.map(([x, y, value]) => [Math.hypot(east - x, north - y), value]);
        const exact = distances.find(([distance]) => distance <= 0.001);
        let value;
        if (exact) value = exact[1];
        else {
          const closest = Math.min(...distances.map(([distance]) => distance));
          const weighted = distances.map(([distance, source]) => [(closest / distance) ** 2, source]);
          value = weighted.reduce((sum, [weight, source]) => sum + weight * source, 0)
            / weighted.reduce((sum, [weight]) => sum + weight, 0);
        }
        const lat = gateway.lat + north / radius / radians;
        const lon = gateway.lon + east / (radius * cos) / radians;
        values.push([lat, lon, value]); points.push([lat, lon, Math.max(0, Math.min(1, value / 100))]);
      }
    }
    return {mode: 'simulation', layer: 'soil_moisture', unit: '%', grid_m: 11,
      generated_at: new Date(now).toISOString(), source_count: sources.length, points, values,
      preview: true, notice: 'Riego local de maqueta; IDW p=2 en metros, no persistido ni recibido por radio.'};
  }

  function twinPosition(node) {
    if (!Number.isFinite(node.east_m) || !Number.isFinite(node.north_m)
        || Math.abs(node.east_m) > 88 || Math.abs(node.north_m) > 88) return null;
    return {x: 400 + node.east_m * 2.5, y: 290 - node.north_m * 2.5};
  }

  function twinVisualState(node, fireNodes = new Set()) {
    // Un sensor sin alimentacion no tiene LED, aunque su alerta siga activa en Gateway.
    return node.state === 'offline' ? 'offline' : nodeVisualState(node, fireNodes);
  }

  // Funciones puras para verificacion opcional de JS, sin Node requerido en ejecucion.
  window.VitiScan = Object.freeze({parseFrame, parentFor, nodeVisualState, nodeLabel, uncertainFailure,
    moistureSource, irrigateSector, irrigationHeatmap, twinPosition, twinVisualState});

  const state = {config: null, token: '', busy: false, nodes: [], alerts: [], map: null,
    markers: new Map(), links: null, heat: null, heatmap: null, selected: 16, frames: [],
    layer: 'soil_moisture', generation: 0, refreshController: null, pendingKeys: new Map(),
    alertTimer: null, networkTimer: null, clockTimer: null, stopped: false, didFit: false,
    irrigation: new Map(), backendHeatmap: null, twinFresh: false};
  const $ = id => document.getElementById(id);
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const format = (value, unit = '', digits = 1) => Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : '—';
  const sensor = (node, field, bit, scale = 1) =>
    node.status_flags == null || node.status_flags & (1 << bit) || !Number.isFinite(node[field]) ? null : node[field] / scale;

  async function fetchJSON(path, options = {}, parentSignal = null) {
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (parentSignal?.aborted) controller.abort();
    parentSignal?.addEventListener('abort', cancel, {once: true});
    const timeout = setTimeout(cancel, 15000);
    try {
      const response = await fetch(path, {...options, cache: 'no-store', credentials: 'same-origin', signal: controller.signal});
      let data;
      try { data = await response.json(); }
      catch (error) {
        if (response.ok) throw new Error('JSON del backend inválido; confirmación indeterminada.');
        data = {};
      }
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : `Respuesta HTTP ${response.status}`;
        throw Object.assign(new Error(detail), {status: response.status});
      }
      return data;
    } finally {
      clearTimeout(timeout);
      parentSignal?.removeEventListener('abort', cancel);
    }
  }

  function connection(ok, message) {
    $('connection').textContent = message;
    $('connection').className = `connection ${ok ? 'online' : 'error'}`;
    $('twin-sync').textContent = ok ? 'ESTADO CONFIRMADO' : 'ÚLTIMO ESTADO · SIN CONEXIÓN';
    $('twin-sync').className = `pill${ok ? ' twin-connected' : ' twin-disconnected'}`;
  }

  function actionMessage(message, error = false) {
    $('action-status').textContent = message;
    $('action-status').className = `status-message${error ? ' error' : ''}`;
    $('twin-action-status').textContent = message;
    $('twin-action-status').className = `status-message${error ? ' error' : ''}`;
  }

  function updateButtons() {
    const authorized = state.config?.auth_mode === 'local_cookie' || Boolean(state.token);
    document.querySelectorAll('[data-action]').forEach(button => {
      button.disabled = state.busy || !state.config?.actions_enabled || !authorized;
    });
    $('demo-panel').setAttribute('aria-busy', String(state.busy));
    $('physical-twin').setAttribute('aria-busy', String(state.busy));
    const branch = Number($('twin-sector').value);
    const wettable = state.nodes.some(node => node.branch === branch && node.level <= 3
      && moistureSource(node) !== null && (state.irrigation.get(node.node_id) ?? node.soil_moisture / 100) < 100);
    $('twin-water').disabled = state.busy || !state.config?.actions_enabled || !authorized || !state.twinFresh || !wettable;
    $('twin-clear-water').disabled = state.busy || !state.irrigation.size;
  }

  function showMapWarning(message) { $('map-warning').hidden = false; $('map-warning').textContent = message; }

  function initMap() {
    if (!window.L) {
      $('map').classList.add('map-error');
      $('map').textContent = 'Leaflet no disponible. Revisa Internet/CDN; los controles y la telemetría siguen operativos.';
      return;
    }
    const gateway = state.config.gateway;
    const map = L.map('map', {zoomControl: true, maxZoom: 22}).setView([gateway.lat, gateway.lon], 19);
    state.map = map;
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxNativeZoom: 19, maxZoom: 22,
    }).on('tileerror', () => showMapWarning('Cartografía externa no disponible. La topología y las capas locales siguen visibles.')).addTo(map);
    map.createPane('networkLinks'); map.getPane('networkLinks').style.zIndex = '410';
    map.createPane('networkNodes'); map.getPane('networkNodes').style.zIndex = '430';
    state.links = L.layerGroup().addTo(map);
    for (const level of [1, 2, 3, 4]) {
      L.circle([gateway.lat, gateway.lon], {radius: level * 22, color: '#7893ae', opacity: 0.22,
        weight: 1, fill: false, dashArray: '3 7', interactive: false}).addTo(map);
    }
    const icon = L.divIcon({html: 'GW', className: 'gateway-icon', iconSize: [32, 32], iconAnchor: [16, 16]});
    L.marker([gateway.lat, gateway.lon], {icon, title: 'Gateway GW-00 · Nivel 0', zIndexOffset: 1000})
      .addTo(map).bindTooltip('GW-00 · N0', {permanent: true, direction: 'top', offset: [0, -16], className: 'node-label'});
    L.control.scale({imperial: false, position: 'bottomright'}).addTo(map);
    map.on('mousemove', event => probeHeatmap(event.latlng));
  }

  function fitNetwork() {
    if (!state.map || !state.nodes.length) return;
    state.map.fitBounds(state.nodes.map(node => [node.lat, node.lon]), {padding: [55, 65], maxZoom: 19});
  }

  function addLink(child, parent, visual, ghost = false) {
    const points = [[child.lat, child.lon], [parent.lat, parent.lon]];
    const backup = visual === 'backup';
    const line = L.polyline(points, {pane: 'networkLinks', color: ghost ? '#ff6174' : COLORS[visual],
      weight: ghost ? 1.5 : backup ? 3 : 2, opacity: ghost ? 0.3 : 0.75,
      dashArray: ghost ? '2 7' : null, className: ghost ? 'failed-link' : `tdma-link${backup ? ' backup-link' : ''}`})
      .addTo(state.links);
    line.bindTooltip(element('span', `${nodeLabel(child.node_id)} → ${nodeLabel(parent.node_id)}${ghost ? ' · primario caído (inactivo)' : backup ? ' · respaldo activo' : child.state === 'seed' ? ' · enlace semilla, no confirmado' : ' · padre operativo'}`));
    const path = line.getElement();
    if (path) { path.dataset.child = String(child.node_id); path.dataset.parent = String(parent.node_id); path.dataset.active = String(!ghost && child.state !== 'seed'); }
  }

  function selectNode(id, pan = false) {
    state.selected = id;
    const node = state.nodes.find(candidate => candidate.node_id === id);
    if (pan && node && state.map) state.map.panTo([node.lat, node.lon]);
    renderNetwork();
  }

  const svgElement = (tag, attributes = {}, text) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function renderTwin() {
    const focusId = document.activeElement?.closest('[data-twin-node]')?.dataset.twinNode;
    const fireNodes = new Set(state.alerts.filter(alert => alert.state === 'active').map(alert => alert.node_id));
    const positions = new Map([[0, {x: 400, y: 290}]]);
    for (const node of state.nodes) { const point = twinPosition(node); if (point) positions.set(node.node_id, point); }
    const links = document.createDocumentFragment(); const nodes = document.createDocumentFragment();
    const patches = document.createDocumentFragment();
    for (const node of state.nodes) {
      const point = positions.get(node.node_id); if (!point) continue;
      const visual = twinVisualState(node, fireNodes); const parent = parentFor(node);
      if (parent !== null && positions.has(parent)) {
        const destination = positions.get(parent);
        links.append(svgElement('path', {d: `M${point.x} ${point.y}L${destination.x} ${destination.y}`,
          class: `twin-route ${visual}`, 'marker-end': 'url(#twin-route-arrow)',
          'data-twin-child': node.node_id, 'data-twin-parent': parent,
          'data-active': node.state !== 'seed'}));
      }
      if (state.irrigation.has(node.node_id) && moistureSource(node) !== null) {
        patches.append(svgElement('circle', {cx: point.x, cy: point.y, r: 25, class: 'twin-wet-patch'}));
      }
      const group = svgElement('g', {transform: `translate(${point.x} ${point.y})`,
        class: `twin-node ${visual}${state.selected === node.node_id ? ' selected' : ''}`,
        role: 'button', tabindex: 0, 'data-twin-node': node.node_id,
        'aria-pressed': state.selected === node.node_id,
        'aria-label': `${nodeLabel(node.node_id)}, nivel ${node.level}, ${STATUS[visual]}${node.node_id === 1 ? ', poste repetidor con switch' : node.node_id === 16 ? ', MQ-2 en perímetro forestal' : ''}`});
      if (node.node_id === 1) {
        group.append(svgElement('path', {d: 'M-3-32H3V-3H-3ZM-13-27H13M-10-35Q0-43 10-35', class: 'twin-pole'}));
      }
      group.append(svgElement('circle', {r: 17, class: 'twin-node-target'}),
        svgElement('circle', {r: 8, class: 'twin-node-led'}),
        svgElement('text', {y: 31, 'text-anchor': 'middle', class: 'twin-node-label'}, nodeLabel(node.node_id)),
        svgElement('title', {}, `${nodeLabel(node.node_id)} · N${node.level} · ${STATUS[visual]} · padre ${parent === null ? 'sin confirmar' : nodeLabel(parent)}`));
      group.addEventListener('click', () => selectNode(node.node_id));
      group.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectNode(node.node_id); }
      });
      nodes.append(group);
    }
    $('twin-links').replaceChildren(links); $('twin-nodes').replaceChildren(nodes);
    $('twin-water-patches').replaceChildren(patches);
    if (focusId) $('twin-nodes').querySelector(`[data-twin-node="${focusId}"]`)?.focus({preventScroll: true});
    const failover = state.nodes.some(node => twinVisualState(node) === 'backup');
    const indicators = [['twin-gateway-led', state.twinFresh ? 'normal' : 'unknown', 'Gateway'],
      ['twin-failover-led', failover ? 'backup' : 'offline', 'Respaldo'],
      ['twin-fire-led', fireNodes.size ? 'fire' : 'offline', 'Alarma']];
    for (const [id, visual, label] of indicators) {
      $(id).className = `twin-led ${visual}`;
      $(id).setAttribute('aria-label', `${label}: ${visual === 'offline' ? 'apagado' : STATUS[visual]}`);
    }
    const pole = state.nodes.find(node => node.node_id === 1);
    const cut = pole?.state === 'offline';
    $('twin-cut-switch').setAttribute('aria-pressed', String(cut));
    $('twin-switch-state').textContent = `Poste V-01: ${cut ? 'SIN ENERGÍA · switch cortado' : pole && ['online', 'sleeping'].includes(pole.state) ? 'ENERGIZADO' : 'sin confirmar'}`;
    const selected = state.nodes.find(node => node.node_id === state.selected);
    if (selected) {
      const baseline = moistureSource(selected); const preview = state.irrigation.get(selected.node_id);
      $('twin-node-detail').textContent = `${nodeLabel(selected.node_id)} · N${selected.level} · ${STATUS[twinVisualState(selected, fireNodes)]} · Humedad recibida: ${format(baseline, ' %')}${preview !== undefined && baseline !== null ? ` · Maqueta local: ${format(preview, ' %')}` : ''}${selected.node_id === 16 ? ' · MQ-2 sintético · escucha de 35 ms' : ''}`;
    }
    updateButtons();
  }

  function waterTwinSector() {
    if ($('twin-water').disabled) return;
    const branch = Number($('twin-sector').value);
    state.irrigation = irrigateSector(state.nodes, state.irrigation, branch);
    const target = state.nodes.find(node => node.branch === branch && node.level <= 3 && moistureSource(node) !== null);
    if (target) state.selected = target.node_id;
    state.layer = 'soil_moisture'; $('heat-layer').value = state.layer;
    state.generation++; state.refreshController?.abort();
    $('heat-visible').checked = true;
    $('twin-irrigation-status').textContent = `Riego LOCAL activo · rama ${branch}, niveles 1–3 · hasta +20 puntos por pulsación (máximo 100%). IDW p=2 recalculado; no hay ingesta ni tramas de riego. Limpiar o Restaurar retira la previsualización.`;
    renderNetwork();
    renderHeatmap(state.backendHeatmap || {layer: state.layer, points: [], values: [], source_count: 0, grid_m: 11});
    actionMessage(`Riego de maqueta en rama ${branch}: humedad e IDW locales actualizados, sin guardar mediciones.`);
    $('map-probe').textContent = 'IDW de riego LOCAL · mueve el cursor para consultar humedad.';
    refresh(true);
  }

  function clearTwinWater() {
    state.irrigation.clear();
    $('twin-irrigation-status').textContent = 'Sin riego local. La malla vuelve a los valores confirmados del backend; no se modificó el historial.';
    renderTwin();
    renderHeatmap(state.backendHeatmap?.layer === state.layer ? state.backendHeatmap
      : {layer: state.layer, points: [], values: [], source_count: 0, grid_m: 11});
  }

  function renderNetwork() {
    const focusedId = document.activeElement?.closest('#node-table tr')?.dataset.nodeId;
    const fireNodes = new Set(state.alerts.filter(alert => alert.state === 'active').map(alert => alert.node_id));
    const activeCount = state.nodes.filter(node => ['online', 'sleeping'].includes(node.state)).length;
    $('active-count').replaceChildren(document.createTextNode(String(activeCount)), element('small', '/20'));
    const table = document.createDocumentFragment();
    if (state.links) state.links.clearLayers();
    const positions = new Map(state.nodes.map(node => [node.node_id, node]));
    if (state.config) positions.set(0, {node_id: 0, ...state.config.gateway});
    for (const node of state.nodes) {
      const visual = nodeVisualState(node, fireNodes);
      const parentId = parentFor(node);
      const row = element('tr'); row.dataset.nodeId = String(node.node_id); row.tabIndex = 0;
      row.className = state.selected === node.node_id ? 'selected' : '';
      row.setAttribute('aria-label', `${nodeLabel(node.node_id)}, nivel ${node.level}, ${STATUS[visual]}`);
      row.append(element('td', `${nodeLabel(node.node_id)} · N${node.level}`), element('td', STATUS[visual], `node-state ${visual}`),
        element('td', parentId == null ? '—' : nodeLabel(parentId)), element('td', format(node.battery_pct, '%', 0)));
      row.addEventListener('click', () => selectNode(node.node_id, true));
      row.addEventListener('keydown', event => { if (event.key === 'Enter') selectNode(node.node_id, true); });
      table.append(row);
      if (!state.map) continue;
      let marker = state.markers.get(node.node_id);
      if (!marker) {
        marker = L.circleMarker([node.lat, node.lon], {pane: 'networkNodes', radius: 8, fillOpacity: 1, weight: 2})
          .addTo(state.map).bindTooltip(nodeLabel(node.node_id), {permanent: true, direction: 'top', offset: [0, -8], className: 'node-label'});
        marker.on('click', () => selectNode(node.node_id));
        state.markers.set(node.node_id, marker);
        const path = marker.getElement();
        path?.setAttribute('tabindex', '0'); path?.setAttribute('role', 'button');
        path?.addEventListener('keydown', event => { if (event.key === 'Enter') selectNode(node.node_id); });
      }
      marker.setStyle({color: COLORS[visual], fillColor: visual === 'offline' || visual === 'unknown' ? '#1c2939' : COLORS[visual],
        radius: visual === 'fire' ? 12 : 8, weight: node.node_id === state.selected ? 4 : 2});
      const path = marker.getElement();
      if (path) {
        path.classList.toggle('node-fire', visual === 'fire'); path.dataset.nodeId = String(node.node_id);
        path.setAttribute('aria-label', `${nodeLabel(node.node_id)} · ${STATUS[visual]}`);
      }
      if (parentId != null && positions.has(parentId)) addLink(node, positions.get(parentId), node.using_backup_parent || node.failover ? 'backup' : node.state === 'seed' ? 'unknown' : 'normal');
      if (node.using_backup_parent && positions.has(node.primary_parent)) addLink(node, positions.get(node.primary_parent), 'offline', true);
    }
    $('node-table').replaceChildren(table);
    if (focusedId) $('node-table').querySelector(`[data-node-id="${focusedId}"]`)?.focus({preventScroll: true});
    renderDetail();
    renderTwin();
    if (!state.didFit && state.nodes.length && state.map) { fitNetwork(); state.didFit = true; }
  }

  function renderDetail() {
    const node = state.nodes.find(candidate => candidate.node_id === state.selected);
    if (!node) return;
    const grid = element('div', undefined, 'detail-grid');
    const entries = [
      ['Humedad suelo', format(sensor(node, 'soil_moisture', 1, 100), ' %')],
      ['Temperatura suelo', format(sensor(node, 'soil_temp_x10', 0, 10), ' °C')],
      ['Temperatura ambiente', format(sensor(node, 'amb_temp_x10', 2, 10), ' °C')],
      ['Gas sintético', format(sensor(node, 'gas_smoke_ppm', 4), ' ppm', 0)],
      ['RSSI del enlace', format(node.rssi_dbm, ' dBm')],
      ['Padre operativo', node.operational_parent_id == null ? '—' : nodeLabel(node.operational_parent_id)],
    ];
    entries.forEach(([label, value]) => grid.append(element('span', `${label}: ${value}`)));
    $('node-detail').replaceChildren(element('strong', `${nodeLabel(node.node_id)} · Nivel ${node.level} · Rama ${node.branch}`), grid,
      element('p', node.last_seen_at ? `Última recepción: ${new Date(node.last_seen_at).toLocaleTimeString('es-BO')}` : 'Sin muestra recibida; valores desconocidos.'));
  }

  function renderAlerts() {
    const active = state.alerts.filter(alert => alert.state === 'active');
    $('fire-banner').hidden = !active.length;
    if (!active.length) { $('rf-latency').textContent = '—'; return; }
    const isRadio = active.some(alert => alert.reason === 'radio_flag');
    $('fire-title').textContent = isRadio ? 'ALERTA ROJA · FIRE_ALERT 0xFF RECIBIDA' : 'ALERTA ROJA · UMBRAL SINTÉTICO DE GAS';
    const origins = [...new Set(active.map(alert => nodeLabel(alert.node_id)))].join(', ');
    $('fire-description').textContent = `${origins} · Evento confirmado por Gateway. Consulta de alertas cada 500 ms; no equivale a garantía RF.`;
    const latency = active.find(alert => Number.isFinite(alert.latency_ms))?.latency_ms;
    $('rf-latency').textContent = format(latency, ' ms', 0);
  }

  function applyAlerts(alerts) {
    if (JSON.stringify(alerts) === JSON.stringify(state.alerts)) return;
    state.alerts = alerts; renderAlerts(); renderNetwork();
  }

  function renderHeatmap(result) {
    state.backendHeatmap = result;
    if (state.layer === 'soil_moisture' && state.irrigation.size && state.config) {
      result = irrigationHeatmap(state.nodes, state.irrigation, state.config.gateway);
    }
    state.heatmap = result;
    if (state.lastProbeLatLng) probeHeatmap(state.lastProbeLatLng);
    else $('map-probe').textContent = result.preview
      ? 'IDW de riego LOCAL · mueve el cursor para consultar humedad.'
      : 'Mueve el cursor para consultar una celda IDW.';
    const layer = LAYERS[state.layer];
    $('heat-unit').textContent = layer.title; $('heat-low').textContent = layer.low; $('heat-high').textContent = layer.high;
    const colors = Object.entries(layer.gradient).sort((a, b) => Number(a[0]) - Number(b[0]));
    $('heat-gradient').style.background = `linear-gradient(90deg, ${colors.map(([stop, color]) => `${color} ${Number(stop) * 100}%`).join(', ')})`;
    $('source-count').textContent = `${result.source_count}/20 fuentes · ${result.points.length} celdas · IDW p=2${result.preview ? ' · RIEGO LOCAL' : ''}`;
    if (!state.map) return;
    if (state.heat) { state.map.removeLayer(state.heat); state.heat = null; }
    if (!$('heat-visible').checked || !result.points.length) return;
    // Una malla IDW es un campo de valores, no un conjunto de eventos: sumar
    // densidad con Leaflet.heat saturaria el color aunque el gas fuera bajo.
    // Canvas conserva cada intensidad normalizada; el suavizado es solo visual.
    const side = Math.round(Math.sqrt(result.points.length));
    const raster = document.createElement('canvas'); raster.width = side; raster.height = side;
    const rasterContext = raster.getContext('2d');
    const image = rasterContext.createImageData(side, side);
    const stops = colors.map(([stop, color]) => [Number(stop), color.match(/[0-9a-f]{2}/gi).map(value => Number.parseInt(value, 16))]);
    result.points.forEach((point, index) => {
      const intensity = Math.max(0, Math.min(1, point[2]));
      const upperIndex = Math.max(1, stops.findIndex(([stop]) => stop >= intensity));
      const lower = stops[upperIndex - 1]; const upper = stops[upperIndex];
      const fraction = (intensity - lower[0]) / (upper[0] - lower[0]);
      const pixel = ((side - 1 - Math.floor(index / side)) * side + index % side) * 4;
      for (let channel = 0; channel < 3; channel++) image.data[pixel + channel] = Math.round(lower[1][channel] + fraction * (upper[1][channel] - lower[1][channel]));
      image.data[pixel + 3] = 165;
    });
    rasterContext.putImageData(image, 0, 0);
    const deltaLat = result.grid_m / 6378137 * 180 / Math.PI;
    const deltaLon = deltaLat / Math.cos(state.config.gateway.lat * Math.PI / 180);
    const first = result.points[0]; const last = result.points[result.points.length - 1];
    const northWest = [last[0] + deltaLat / 2, first[1] - deltaLon / 2];
    const southEast = [first[0] - deltaLat / 2, last[1] + deltaLon / 2];
    const CanvasGrid = L.Layer.extend({
        onAdd(map) {
          this._map = map; this._canvas = L.DomUtil.create('canvas', 'leaflet-layer');
          this._canvas.style.pointerEvents = 'none';
          map.getPanes().overlayPane.appendChild(this._canvas);
          map.on('moveend zoomend resize', this.draw, this); this.draw();
        },
        onRemove(map) { map.off('moveend zoomend resize', this.draw, this); this._canvas.remove(); },
        draw() {
          const size = this._map.getSize(); const canvas = this._canvas;
          canvas.width = size.x; canvas.height = size.y;
          L.DomUtil.setPosition(canvas, this._map.containerPointToLayerPoint([0, 0]));
          const context = canvas.getContext('2d');
          const topLeft = this._map.latLngToContainerPoint(northWest);
          const bottomRight = this._map.latLngToContainerPoint(southEast);
          context.imageSmoothingEnabled = true;
          context.drawImage(raster, topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y);
        },
    });
    state.heat = new CanvasGrid().addTo(state.map);
  }

  function probeHeatmap(latlng) {
    state.lastProbeLatLng = latlng;
    if (!state.heatmap?.values?.length) {
      $('map-probe').textContent = 'Sin celdas IDW válidas en la capa seleccionada.';
      return;
    }
    let best = null; let distance = Infinity;
    for (const cell of state.heatmap.values) {
      const d = (cell[0] - latlng.lat) ** 2 + ((cell[1] - latlng.lng) * Math.cos(latlng.lat * Math.PI / 180)) ** 2;
      if (d < distance) { distance = d; best = cell; }
    }
    $('map-probe').textContent = best && distance < 0.0003 ** 2
      ? `Celda IDW${state.heatmap.preview ? ' · LOCAL' : ''}: ${format(best[2], ' ' + LAYERS[state.layer].unit)} · ${best[0].toFixed(5)}, ${best[1].toFixed(5)}`
      : 'Fuera de la malla del viñedo.';
  }

  function showFrame(index) {
    const packet = state.frames[index];
    if (!packet) return;
    try {
      const frame = parseFrame(packet.payload_hex);
      const fragment = document.createDocumentFragment();
      const headerFields = ['Magic 0xA5', 'Tipo de mensaje', 'Nivel del emisor', 'ID del emisor', 'ID del padre / broadcast', 'Cantidad de lecturas'];
      for (let groupIndex = -1; groupIndex < frame.count; groupIndex++) {
        const header = groupIndex === -1; const offset = header ? 0 : 6 + groupIndex * 12;
        const group = element('div', undefined, 'hex-group');
        group.append(element('span', header ? 'HDR' : nodeLabel(frame.readings[groupIndex].node_id), 'hex-group-label'));
        const names = ['node_id', 'soil_temp (LSB)', 'soil_temp (MSB)', 'soil_moisture (LSB)', 'soil_moisture (MSB)',
          'amb_temp (LSB)', 'amb_temp (MSB)', 'amb_humidity', 'gas (LSB)', 'gas (MSB)', 'battery_pct', 'status_flags'];
        Array.from(frame.bytes.slice(offset, offset + (header ? 6 : 12))).forEach((byte, i) => {
          const span = element('span', byte.toString(16).padStart(2, '0').toUpperCase(), `hex-byte${header ? ' header-byte' : ''}`);
          span.title = header ? headerFields[i] : names[i]; group.append(span);
        });
        fragment.append(group);
      }
      $('hex-viewer').replaceChildren(fragment);
      $('packet-size').textContent = `${frame.bytes.length} B · 6 + ${frame.count} × 12`;
      $('frame-description').textContent = `${MESSAGE_TYPES[frame.type]} (0x${frame.type.toString(16).toUpperCase().padStart(2, '0')}) · N${frame.level} · ${nodeLabel(frame.sender)} → ${frame.parent === 255 ? 'BROADCAST' : nodeLabel(frame.parent)} · ${frame.count} lecturas · Epoch HTTP externo: ${packet.cycle_id}`;
    } catch (error) { $('hex-viewer').replaceChildren(element('p', error.message, 'status-message error')); }
  }

  function showPackets(packets) {
    state.frames = packets;
    const select = $('frame-select'); select.replaceChildren(); select.disabled = !packets.length;
    packets.forEach((packet, index) => {
      const frame = parseFrame(packet.payload_hex);
      const option = element('option', `${index + 1}. ${MESSAGE_TYPES[frame.type]} · ${nodeLabel(frame.sender)} · ${frame.bytes.length} B · ${frame.count} lecturas`);
      option.value = String(index); select.append(option);
    });
    select.value = String(Math.max(0, packets.length - 1)); showFrame(packets.length - 1);
  }

  async function refresh(force = false) {
    if (state.refreshController && !force) return;
    if (force) state.refreshController?.abort();
    const controller = new AbortController(); state.refreshController = controller;
    const generation = state.generation; const layer = state.layer;
    try {
      const requests = [fetchJSON('/api/v1/nodes/status?mode=simulation', {}, controller.signal),
        fetchJSON(`/api/v1/heatmap/${layer}?mode=simulation`, {}, controller.signal)];
      if (force) requests.push(fetchJSON('/api/v1/alerts/fire?mode=simulation', {}, controller.signal));
      const [network, heat, alerts] = await Promise.all(requests);
      if (state.generation !== generation || state.layer !== layer || controller.signal.aborted) return;
      state.nodes = network.nodes;
      state.twinFresh = true;
      if (alerts) state.alerts = alerts.alerts;
      renderNetwork(); renderAlerts(); renderHeatmap(heat); connection(true, 'Gateway conectado');
    } catch (error) {
      if (error.name !== 'AbortError' && generation === state.generation) {
        state.twinFresh = false; renderTwin(); connection(false, 'Sin conexión · conservando último estado');
      }
    } finally { if (state.refreshController === controller) state.refreshController = null; }
  }

  async function pollAlerts() {
    if (state.stopped) return;
    const generation = state.generation;
    try {
      if (!state.busy) {
        const result = await fetchJSON('/api/v1/alerts/fire?mode=simulation');
        if (generation === state.generation && !state.busy) applyAlerts(result.alerts);
      }
    } catch (error) { connection(false, 'Alertas sin actualizar · revisar conexión'); }
    if (!state.stopped) state.alertTimer = setTimeout(pollAlerts, state.config?.alert_poll_ms || 500);
  }

  async function pollNetwork() {
    if (state.stopped) return;
    if (!state.busy) await refresh();
    if (!state.stopped) state.networkTimer = setTimeout(pollNetwork, 2000);
  }

  async function runAction(action) {
    if (state.busy) return;
    state.busy = true; state.generation++; state.refreshController?.abort(); updateButtons();
    const started = performance.now();
    actionMessage(`Ejecutando ${action}… esperando confirmación del Gateway.`);
    try {
      const key = state.pendingKeys.get(action) || crypto.randomUUID(); state.pendingKeys.set(action, key);
      const headers = {'Content-Type': 'application/json'};
      if (state.token) headers.Authorization = `Bearer ${state.token}`;
      const result = await fetchJSON('/api/v1/sim/trigger', {method: 'POST', headers,
        body: JSON.stringify({action, idempotency_key: key, mode: 'simulation'})});
      if (!['completed', 'partial'].includes(result.status) || !Array.isArray(result.packets)) {
        throw new Error('Resultado incompleto; no se puede confirmar la simulación.');
      }
      result.packets.forEach(packet => parseFrame(packet.payload_hex));
      state.pendingKeys.delete(action); state.generation++;
      $('web-latency').textContent = `${Math.round(performance.now() - started)} ms`;
      if (Number.isFinite(result.latency_ms)) $('rf-latency').textContent = format(result.latency_ms, ' ms', 0);
      // Solo encender rojo DESPUES de recibir un 0xFF real confirmado por backend.
      const firePacket = result.packets.find(packet => packet.msg_type === 255);
      if (firePacket) {
        const frame = parseFrame(firePacket.payload_hex);
        applyAlerts([{node_id: frame.readings[0].node_id, state: 'active', reason: 'radio_flag', latency_ms: result.latency_ms}]);
      } else if (action === 'restore') applyAlerts([]);
      if (action === 'restore') clearTwinWater();
      showPackets(result.packets);
      if (action === 'failover') actionMessage('19/20 recuperados · V-01 caído · V-06 → V-02 por respaldo.');
      else if (action === 'fire') actionMessage('FIRE_ALERT 0xFF confirmado · foco V-16 · escucha de 35 ms validada.');
      else if (action === 'restore') actionMessage(`Red demo restaurada: 20/20 · ${result.closed_demo_alerts} alertas demo cerradas; historial conservado.`);
      else actionMessage('Cascada nominal completa: 20/20 · ACK y slots verificados.');
      if (action === 'fire') { state.layer = 'gas_smoke_ppm'; $('heat-layer').value = state.layer; state.selected = 16; }
      await refresh(true);
    } catch (error) {
      if (!uncertainFailure(error)) state.pendingKeys.delete(action);
      actionMessage(error.status === 403 ? `${error.message} Habilita SIM_ACTIONS_ENABLED=true.`
        : error.status === 401 ? `${error.message} Recarga la página o revisa el token de operador.`
          : `${error.message || 'No hay confirmación.'}${uncertainFailure(error) ? ' Estado incierto: se conserva la identidad; no se repetirá como una acción nueva.' : ''}`, true);
    } finally { state.busy = false; updateButtons(); }
  }

  async function boot() {
    document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => runAction(button.dataset.action)));
    $('twin-water').addEventListener('click', waterTwinSector);
    $('twin-clear-water').addEventListener('click', () => { clearTwinWater(); refresh(true); });
    $('twin-sector').addEventListener('change', updateButtons);
    $('frame-select').addEventListener('change', event => showFrame(Number(event.target.value)));
    $('fit-network').addEventListener('click', fitNetwork);
    $('heat-layer').addEventListener('change', () => {
      state.layer = $('heat-layer').value; state.generation++;
      renderHeatmap({layer: state.layer, points: [], values: [], source_count: 0, grid_m: 11});
      $('source-count').textContent = 'Actualizando malla…'; $('map-probe').textContent = 'Esperando la capa seleccionada.';
      refresh(true);
    });
    $('heat-visible').addEventListener('change', () => { if (state.backendHeatmap?.layer === state.layer) renderHeatmap(state.backendHeatmap); });
    $('token-form').addEventListener('submit', event => {
      event.preventDefault(); state.token = $('operator-token').value.trim(); $('operator-token').value = '';
      $('auth-state').textContent = state.token ? 'TOKEN EN MEMORIA' : 'SIN TOKEN'; updateButtons();
      actionMessage('Token conservado solo en memoria; se verificará al ejecutar una acción.');
    });
    const tick = () => { $('clock').textContent = new Date().toLocaleTimeString('es-BO', {timeZone: 'America/La_Paz'}); };
    tick(); state.clockTimer = setInterval(tick, 1000);
    try {
      state.config = await fetchJSON('/api/v1/dashboard/config');
      $('auth-state').textContent = state.config.auth_mode === 'local_cookie' ? 'SESIÓN LOCAL' : 'BEARER REQUERIDO';
      $('token-form').hidden = state.config.auth_mode === 'local_cookie';
      updateButtons(); initMap();
      actionMessage(state.config.actions_enabled ? 'Listo. Cada botón ejecuta un escenario independiente.' : 'Acciones deshabilitadas. Usa el arranque demo local o SIM_ACTIONS_ENABLED=true.');
      await refresh(true); pollAlerts(); pollNetwork();
    } catch (error) { connection(false, 'Servidor no disponible'); actionMessage(`No se pudo iniciar: ${error.message}. Recarga cuando esté disponible.`, true); }
  }

  document.addEventListener('DOMContentLoaded', boot);
  window.addEventListener('pagehide', () => {
    state.stopped = true; state.token = ''; state.refreshController?.abort();
    clearTimeout(state.alertTimer); clearTimeout(state.networkTimer); clearInterval(state.clockTimer);
  });
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
})();
