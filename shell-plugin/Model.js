// Plain JavaScript: shared by QML and the dependency-free Node tests.
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
