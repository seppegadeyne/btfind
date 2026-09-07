const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
test('WiFi panel has bounded polling, explicit probe, presence-only UI and IPC', () => {
 const qml = fs.readFileSync(path.join(__dirname,'../shell-plugin/BtFind.qml'),'utf8');
 assert.match(qml, /interval: 20000/);
 assert.match(qml, /wifi-scan\.py/);
 assert.match(qml, /Model\.parseWifi/);
 assert.match(qml, /Model\.wifiRows/);
 assert.match(qml, /function wifi\(\)/);
 assert.match(qml, /Scan subnet/);
 assert.match(qml, /geen afstand/);
});
test('plugin exposes native coordinated panel, not a terminal launcher', () => {
 const qml = fs.readFileSync(path.join(__dirname,'../shell-plugin/BtFind.qml'),'utf8');
 assert.match(qml, /KeyboardPanel\s*\{/);
 assert.match(qml, /onTabRequested/);
 assert.doesNotMatch(qml, /floating-terminal|execDetached/);
 assert.match(qml, /atomicWrites: true/);
 assert.match(qml, /scan off/);
});
