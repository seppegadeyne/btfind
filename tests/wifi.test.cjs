const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = vm.createContext({});
vm.runInContext(fs.readFileSync(`${__dirname}/../shell-plugin/Model.js`, 'utf8'), model);
test('WiFi history preserves first/last confirmation, expires and isolates network changes', () => {
 const store = {};
 const d = {key:'net|mac',network:'net',ip:'192.168.1.3',mac:'AA:BB:CC:DD:EE:FF',name:'Phone',online:true};
 model.updateWifi(store,{devices:[d],networks:[{identity:'net'}]},1000);
 model.updateWifi(store,{devices:[{...d,online:null}],networks:[{identity:'net'}]},2000);
 let rows = model.wifiRows(store,2000);
 assert.equal(rows[0].first,1000); assert.equal(rows[0].last,1000);
 assert.equal(rows[0].status,'ONBEKEND');
 assert.equal(model.wifiRows(store,92000)[0].status,'OFFLINE?');
 model.updateWifi(store,{devices:[],networks:[{identity:'other'}]},93000);
 assert.equal(model.wifiRows(store,93000).length,0);
});
const network = {iface:'wlan0', cidr:'192.168.1.2/24', network:'192.168.1.0/24', identity:'wlan0|ap|192.168.1.0/24'};
const snapshot = (neighbors, mdns='') => JSON.stringify({networks:[network], neighbors, mdns, names:{}});
test('WiFi merges same-subnet ARP and escaped mDNS names without trusting stale entries', () => {
 const result = model.parseWifi(snapshot([
  {dev:'wlan0',dst:'192.168.1.3',lladdr:'aa:bb:cc:dd:ee:ff',state:['REACHABLE']},
  {dev:'docker0',dst:'192.168.1.4',lladdr:'aa:bb:cc:dd:ee:04',state:['REACHABLE']},
  {dev:'wlan0',dst:'10.0.0.1',lladdr:'aa:bb:cc:dd:ee:05',state:['REACHABLE']},
  {dev:'wlan0',dst:'192.168.1.6',lladdr:'aa:bb:cc:dd:ee:06',state:['STALE']}
 ], '=;wlan0;IPv4;Phone;_test._tcp;local;My\\032Phone.local;192.168.1.3;80;'));
 assert.equal(result.devices.length, 2);
 assert.equal(result.devices[0].mac,'AA:BB:CC:DD:EE:FF');
 assert.equal(result.devices[0].name,'My Phone.local');
 assert.equal(result.devices[0].online,true);
 assert.equal(result.devices[1].online,null);
 assert.equal(model.parseWifi('not json'),null);
});
test('WiFi and BT labels fall back to OUI vendor when hostname is unknown', () => {
 const snap = {networks:[{iface:'w',cidr:'10.0.0.9/24',identity:'w|a|10.0.0.0/24'}],
   neighbors:[{dev:'w',dst:'10.0.0.1',lladdr:'78:8a:20:bc:67:9a',state:['REACHABLE']}],
   names:{}, vendors:{'10.0.0.1':'Ubiquiti Inc'}};
 const store = {};
 model.updateWifi(store, model.parseWifi(JSON.stringify(snap)), 1000);
 const row = model.wifiRows(store, 2000)[0];
 assert.equal(row.vendor, 'Ubiquiti Inc');
 assert.equal(row.label, 'Ubiquiti Inc · 10.0.0.1');
 const devices = {};
 model.update(devices, {mac:'AA:BB:CC:DD:EE:FF', name:'', rssi:-60}, 1000);
 devices['AA:BB:CC:DD:EE:FF'].metadata = {addressType:'public'};
 const bt = model.rows(devices, {}, 2000, {'AA:BB:CC:DD:EE:FF':'Apple, Inc.'})[0];
 assert.equal(bt.label, 'Apple, Inc. · EE:FF');
 assert.equal(bt.named, false);
 assert.equal(bt.vendor, 'Apple, Inc.');
});
