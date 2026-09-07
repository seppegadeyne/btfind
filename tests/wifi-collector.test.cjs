const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
test('collector selects associated WiFi only and caps opt-in probes without root', () => {
 const code = `
import importlib.util, json
spec = importlib.util.spec_from_file_location('wifi', 'shell-plugin/wifi-scan.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
calls = []
def run(args, timeout=3):
 calls.append(args)
 if args == ['iw','dev']: return 'Interface wlan0\\n'
 if args[:4] == ['iw','dev','wlan0','link']: return 'Connected to aa:bb:cc:dd:ee:ff (on wlan0)\\n'
 if args[:3] == ['ip','-j','-4']: return json.dumps([{'ifname':'wlan0','addr_info':[{'family':'inet','local':'192.168.1.2','prefixlen':24}]}])
 if 'neigh' in args: return '[]'
 return ''
m.run = run
s = m.collect(False)
assert len(s['networks']) == 1
assert not any(c[0] == 'ping' for c in calls)
assert s['networks'][0]['network'] == '192.168.1.0/24'
s = m.collect(True)
pings = [c for c in calls if c[0] == 'ping']
assert len(pings) == 253
assert all(c[-1] != '192.168.1.2' for c in pings)
assert all(c[0] not in ('sudo','arp-scan','nmcli') for c in calls)
assert len(m.probe_targets([{'iface':'wlan0','cidr':'10.0.0.2/16'}])) == 0
`;
 const result = spawnSync('python3',['-c',code],{cwd:path.join(__dirname,'..'),encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);
});
