// Plain JavaScript: shared by QML and the dependency-free Node tests.
function wifiAddress(ip) {
    var p = String(ip).split('.');
    if (p.length !== 4 || p.some(function(v) { return !/^\d{1,3}$/.test(v) || Number(v) > 255; })) return null;
    return p.reduce(function(n,v) { return n * 256 + Number(v); }, 0);
}
function wifiContains(cidr, ip) {
    var p = String(cidr).split('/'), a = wifiAddress(p[0]), b = wifiAddress(ip), bits = Number(p[1]);
    if (p.length !== 2 || a === null || b === null || !Number.isInteger(bits) || bits < 0 || bits > 32) return false;
    var size = Math.pow(2, 32-bits);
    return Math.floor(a/size) === Math.floor(b/size);
}
function parseWifi(raw) {
    var s;
    try { s = JSON.parse(raw); } catch (e) { return null; }
    if (!s || !Array.isArray(s.networks) || !Array.isArray(s.neighbors)) return null;
    var found = {}, names = s.names || {};
    function networkFor(iface, ip) {
        return s.networks.find(function(n) { return n.iface === iface && wifiContains(n.cidr, ip) && n.cidr.split('/')[0] !== ip; });
    }
    s.neighbors.forEach(function(n) {
        var net = networkFor(n.dev, n.dst);
        if (!net || !/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(n.lladdr || '')) return;
        var state = Array.isArray(n.state) ? n.state : [n.state];
        found[n.dev+'|'+n.dst] = {key:net.identity+'|'+n.lladdr.toUpperCase(), network:net.identity,
            iface:n.dev, ip:n.dst, mac:n.lladdr.toUpperCase(), name:names[n.dst] || '',
            online:state.indexOf('REACHABLE') >= 0 ? true : state.indexOf('FAILED') >= 0 ? false : null};
    });
    String(s.mdns || '').split('\n').forEach(function(line) {
        var p = line.split(';');
        if (p[0] !== '=' || p.length < 9) return;
        var net = networkFor(p[1], p[7]);
        if (!net) return;
        var key = p[1]+'|'+p[7], d = found[key];
        if (!d) d = found[key] = {key:net.identity+'|'+p[7], network:net.identity, iface:p[1], ip:p[7], mac:'', name:'', online:null};
        if (!d.name) d.name = p[6].replace(/\\(\d{3})/g, function(_,v) { return String.fromCharCode(Number(v)); }).slice(0,120);
    });
    return {devices:Object.keys(found).map(function(k) {return found[k];}), networks:s.networks, message:String(s.message || '')};
}
function updateWifi(store, snapshot, now) {
    var active = snapshot.networks.map(function(n) {return n.identity;});
    Object.keys(store).forEach(function(k) {
        if (active.indexOf(store[k].network) < 0 || now-store[k].observed > 1800000) delete store[k];
        else store[k].online = null;
    });
    snapshot.devices.forEach(function(d) {
        var old = store[d.key];
        // Upgrade an mDNS-only address once ARP supplies its MAC.
        var provisional = d.network+'|'+d.ip;
        if (!old && d.mac && store[provisional]) {old = store[provisional]; delete store[provisional];}
        store[d.key] = Object.assign({}, d, {name:d.name || (old ? old.name : ''),
            first:old ? old.first : now, last:d.online === true ? now : old ? old.last : null, observed:now});
    });
}
function wifiRows(store, now) {
    return Object.keys(store).map(function(k) {
        var d = store[k], expired = now-(d.last === null ? d.first : d.last) > 90000;
        return Object.assign({}, d, {label:d.name || d.ip,
            status:d.online === true && !expired ? 'ONLINE' : d.online === false || expired ? 'OFFLINE?' : 'ONBEKEND'});
    }).sort(function(a,b) {return (b.status === 'ONLINE')-(a.status === 'ONLINE') || a.label.localeCompare(b.label);});
}
function update(devices, event, now) {
    var d = devices[event.mac];
    if (!d) d = devices[event.mac] = {mac:event.mac, name:'', samples:[], ema:null, last:0, rssi:null};
    if (event.name) d.name = event.name;
    if (event.rssi !== null && event.rssi !== undefined) {
        d.ema = d.ema === null || now - d.last > 15000 ? event.rssi : d.ema + 0.35 * (event.rssi - d.ema);
        d.rssi = event.rssi; d.last = now;
        d.samples.push({t:now, r:event.rssi, ema:d.ema});
    }
    d.samples = d.samples.filter(function(s) { return now - s.t <= 90000; }).slice(-600);
}
function rows(devices, aliases, now) {
    return Object.keys(devices).map(function(mac) {
        var d = devices[mac], recent = d.samples.filter(function(s) { return now - s.t <= 15000; });
        var history = d.samples.filter(function(s) { return now - s.t <= 90000; });
        var trend = history.filter(function(s) { return now - s.t <= 10000; });
        var delta = trend.length > 1 ? d.ema - trend[0].ema : 0;
        var name = aliases[mac] || d.name;
        return {mac:mac, label:name || '• ' + mac.slice(-5), named:!!name,
            rssi:d.rssi, ema:d.ema, last:d.last, history:history,
            stale:!d.last || now - d.last > 5000,
            average:recent.length ? recent.reduce(function(n,s) {return n+s.r;},0)/recent.length : null,
            trend:delta > 2 ? '▲ sterker' : delta < -2 ? '▼ zwakker' : '◆ stabiel'};
    }).sort(function(a,b) { return (b.average === null ? -999 : b.average) - (a.average === null ? -999 : a.average) || a.mac.localeCompare(b.mac); });
}
function infoName(raw, mac) {
    var text = clean(raw), alias = text.match(/(?:^|\n)\s*Alias: (.*)/), name = text.match(/(?:^|\n)\s*Name: (.*)/);
    return humanName(alias ? alias[1] : '',mac) || humanName(name ? name[1] : '',mac);
}
function ratio(rssi) { return rssi === null ? 0 : Math.max(0, Math.min(1, (rssi+100)/65)); }
function quality(rssi) {
    if (rssi === null) return 'GEEN SIGNAAL';
    return rssi >= -55 ? 'ZEER DICHTBIJ' : rssi >= -65 ? 'DICHTBIJ' : rssi >= -75 ? 'ZELFDE RUIMTE' : rssi >= -85 ? 'NABIJ' : 'VER / ZWAK';
}
function clean(text) { return String(text).replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, '').replace(/\r/g, ''); }
function humanName(name, mac) {
    name = String(name || '').trim();
    return !name || name.toUpperCase().replace(/-/g, ':') === mac.toUpperCase() ? '' : name;
}
function parseLine(raw) {
    var match = clean(raw).match(/\[(NEW|CHG|DEL)\] Device ([0-9A-F:]{17})\s*(.*)/i);
    if (!match) return null;
    var text = match[3], r = text.match(/RSSI:\s*(?:0x[0-9a-f]+\s*\((-?\d+)\)|(-?\d+))/i);
    var rssi = r ? Number(r[1] || r[2]) : null;
    if (rssi !== null && (rssi >= 0 || rssi < -127)) rssi = null;
    var name = /^(Name|Alias): /.test(text) ? text.replace(/^(Name|Alias): /, '') : (match[1] === 'NEW' && text.indexOf(':') < 0 ? text : '');
    return {mac: match[2].toUpperCase(), name: humanName(name, match[2]), rssi: rssi, removed: match[1] === 'DEL'};
}
