/* Verificacion opcional con Node; no interviene en el arranque del dashboard. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = {window: {addEventListener() {}}, document: {addEventListener() {}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/frontend/app.js'), 'utf8'), context);
const {parseFrame, parentFor, nodeVisualState, nodeLabel} = context.window.VitiScan;

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
const fire = Buffer.from('a5ff0101ff0110e600e30d1f013ec2015fc0', 'hex');
const fireFrame = parseFrame(fire.toString('hex'));
assert.equal(fireFrame.type, 255);
assert.equal(fireFrame.count, 1);
assert.equal(fireFrame.readings[0].node_id, 16);
assert.equal(fireFrame.readings[0].gas_smoke_ppm, 450);
console.log('JS OK: padres operativos, Gateway 0, failover, alerta y 6B/12B/246B little-endian.');
