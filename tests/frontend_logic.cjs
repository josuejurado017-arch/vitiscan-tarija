/* Verificacion opcional con Node; no interviene en el arranque del dashboard. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = {window: {addEventListener() {}}, document: {addEventListener() {}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/frontend/app.js'), 'utf8'), context);
const {parseFrame, parentFor, nodeVisualState, nodeLabel, uncertainFailure} = context.window.VitiScan;
assert.equal(uncertainFailure({status: 503}), true);
assert.equal(uncertainFailure({status: 409}), true);
assert.equal(uncertainFailure({}), true);
assert.equal(uncertainFailure({status: 401}), false);

const nominal = {node_id: 6, state: 'online', primary_parent: 1, operational_parent_id: 1};
assert.equal(parentFor(nominal), 1);
assert.equal(parentFor({...nominal, operational_parent_id: 2, using_backup_parent: true}), 2);
assert.equal(parentFor({...nominal, node_id: 1, operational_parent_id: 0}), 0);
assert.equal(parentFor({...nominal, state: 'offline', operational_parent_id: null}), null);
assert.equal(parentFor({...nominal, state: 'orphan', operational_parent_id: null}), null);
assert.equal(parentFor({...nominal, operational_parent_id: null}), null);
assert.equal(parentFor({...nominal, state: 'seed', operational_parent_id: null}), 1);
assert.equal(nodeVisualState(nominal), 'normal');
assert.equal(nodeVisualState({...nominal, using_backup_parent: true}), 'backup');
assert.equal(nodeVisualState({...nominal, state: 'offline'}), 'offline');
assert.equal(nodeVisualState({...nominal, state: 'seed'}), 'unknown');
assert.equal(nodeVisualState(nominal, new Set([6])), 'fire');
assert.equal(nodeLabel(0), 'GW-00');
assert.equal(nodeLabel(16), 'V-16');

const payload = Buffer.alloc(246);
payload.set([0xa5, 2, 1, 1, 0, 20]);
for (let i = 0; i < 20; i++) {
  const offset = 6 + i * 12;
  payload[offset] = i + 1;
  payload.writeInt16LE(-550, offset + 1);
  payload.writeUInt16LE(4230, offset + 3);
  payload.writeInt16LE(-400, offset + 5);
  payload[offset + 7] = 62;
  payload.writeUInt16LE(1000, offset + 8);
  payload[offset + 10] = 95;
  payload[offset + 11] = 128;
}
const frame = parseFrame(payload.toString('hex'));
assert.equal(frame.bytes.length, 246);
assert.equal(frame.count, 20);
assert.equal(frame.readings[0].soil_temp_x10, -550);
assert.equal(frame.readings[0].amb_temp_x10, -400);
assert.equal(frame.readings[0].soil_moisture, 4230);
assert.equal(frame.readings[0].gas_smoke_ppm, 1000);
assert.equal(frame.readings[19].node_id, 20);
assert.equal(Buffer.from(frame.bytes).toString('hex'), payload.toString('hex'));
for (const hex of ['', 'zz', 'a', '00 02 01 01 00 00', payload.toString('hex') + '00']) {
  assert.throws(() => parseFrame(hex));
}
const duplicate = Buffer.from(payload); duplicate[18] = 1;
assert.throws(() => parseFrame(duplicate.toString('hex')));
const wrongLevel = Buffer.from(payload); wrongLevel[2] = 4;
assert.throws(() => parseFrame(wrongLevel.toString('hex')));
const outOfRange = Buffer.from(payload); outOfRange.writeUInt16LE(1001, 14);
assert.throws(() => parseFrame(outOfRange.toString('hex')));
const fire = Buffer.from('a5ff0101ff0110e600e30d1f013ec2015fc0', 'hex');
const fireFrame = parseFrame(fire.toString('hex'));
assert.equal(fireFrame.type, 255);
assert.equal(fireFrame.count, 1);
assert.equal(fireFrame.readings[0].node_id, 16);
assert.equal(fireFrame.readings[0].gas_smoke_ppm, 450);
const {moistureSource, irrigateSector, irrigationHeatmap, twinPosition, twinVisualState} = context.window.VitiScan;
const now = Date.parse('2026-11-11T12:00:00Z');
const gateway = {lat: -21.6485, lon: -64.6342};
const row = (id, east, north, moisture = 3000) => ({node_id: id, state: 'online',
  branch: (id - 1) % 5 + 1, level: levelForTest(id), east_m: east, north_m: north,
  lat: gateway.lat + north / 6378137 * 180 / Math.PI,
  lon: gateway.lon + east / (6378137 * Math.cos(gateway.lat * Math.PI / 180)) * 180 / Math.PI,
  soil_moisture: moisture, status_flags: 128, last_seen_at: new Date(now).toISOString()});
function levelForTest(id) { return Math.floor((id - 1) / 5) + 1; }
const sources = [row(1, 22, 0), row(6, 44, 0, 4000), row(11, 66, 0, 5000),
  row(16, 88, 0, 1000), row(2, 6.798374, 20.923243, 4500)];
const before = JSON.stringify(sources);
assert.equal(moistureSource(sources[0], now), 30);
for (const bad of [{state: 'offline'}, {state: 'stale'}, {state: 'seed'}, {status_flags: 130},
  {soil_moisture: 10001}, {soil_moisture: NaN}, {status_flags: null}, {lat: Infinity},
  {last_seen_at: new Date(now - 3600001).toISOString()},
  {last_seen_at: new Date(now + 5001).toISOString()}, {last_seen_at: null}]) {
  assert.equal(moistureSource({...sources[0], ...bad}, now), null);
}
const dry = new Map();
const wet = irrigateSector(sources, dry, 1, now);
assert.equal(dry.size, 0, 'El riego no muta su entrada');
assert.equal(JSON.stringify(sources), before, 'No falsificar telemetria del backend');
assert.equal(wet.size, 3); assert.equal(wet.get(1), 50); assert.equal(wet.get(6), 60);
assert.equal(wet.get(11), 70); assert.equal(wet.has(16), false, 'No regar bosque N4');
assert.equal(wet.has(2), false, 'No regar otra rama');
let saturated = wet;
for (let i = 0; i < 8; i++) saturated = irrigateSector(sources, saturated, 1, now);
assert.equal(saturated.get(1), 100); assert.equal(saturated.get(11), 100);
assert.throws(() => irrigateSector(sources, dry, 0, now));
assert.equal(irrigateSector([{...sources[0], state: 'offline'}], dry, 1, now).size, 0);
const originalHeat = irrigationHeatmap(sources, dry, gateway, now);
const wetHeat = irrigationHeatmap(sources, wet, gateway, now);
assert.equal(wetHeat.preview, true); assert.equal(wetHeat.source_count, 5);
assert.equal(wetHeat.points.length, 289); assert.equal(wetHeat.grid_m, 11);
assert.equal(wetHeat.layer, 'soil_moisture');
const east22 = 8 * 17 + 10; // north=0, east=22, coincidencia de fuente <=1 mm
assert.equal(originalHeat.values[east22][2], 30);
assert.equal(wetHeat.values[east22][2], 50);
assert.equal(wetHeat.points[east22][2], .5);
assert.ok(wetHeat.points.every(point => point.every(Number.isFinite) && point[2] >= 0 && point[2] <= 1));
assert.ok(wetHeat.values.every((cell, index) => cell[2] >= originalHeat.values[index][2] - 1e-10));
assert.equal(irrigationHeatmap([], wet, gateway, now).points.length, 0);
assert.equal(irrigationHeatmap(sources, wet, gateway, now + 3600001).source_count, 0);
assert.throws(() => irrigationHeatmap(sources, new Map([[1, 101]]), gateway, now));
assert.throws(() => irrigationHeatmap(sources, wet, {lat: NaN, lon: 0}, now));
assert.equal(twinPosition(sources[0]).x, 455); assert.equal(twinPosition(sources[0]).y, 290);
assert.equal(twinPosition({east_m: 89, north_m: 0}), null);
assert.equal(twinVisualState({...nominal, state: 'offline'}, new Set([6])), 'offline');
assert.equal(twinVisualState({...nominal, using_backup_parent: true}), 'backup');
assert.equal(twinVisualState(nominal, new Set([6])), 'fire');
console.log('JS OK: protocolo, padres, LEDs, escala, riego sectorial local e IDW p=2 sin mutar telemetria.');
