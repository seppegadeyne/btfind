const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
test('plugin exposes native coordinated panel, not a terminal launcher', () => {
 const qml = fs.readFileSync(path.join(__dirname,'../shell-plugin/BtFind.qml'),'utf8');
 assert.match(qml, /KeyboardPanel\s*\{/);
 assert.match(qml, /onTabRequested/);
 assert.doesNotMatch(qml, /floating-terminal|execDetached/);
 assert.match(qml, /atomicWrites: true/);
 assert.match(qml, /scan off/);
});
