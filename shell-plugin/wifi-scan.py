#!/usr/bin/env python3
"""Bounded unprivileged collection only; device parsing/history lives in Model.js."""
import concurrent.futures
import ipaddress
import json
import re
import shutil
import subprocess
import sys


def run(args, timeout: float = 3):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if p.returncode and args[0] in ('ip', 'iw'):
            raise RuntimeError(p.stderr.strip() or ' '.join(args) + ' failed')
        return p.stdout
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
    except FileNotFoundError:
        if args[0] in ('ip', 'iw'):
            raise RuntimeError(args[0] + ' ontbreekt')
        return ''


def probe_targets(networks):
    targets = []
    for n in networks:
        address = ipaddress.ip_interface(n['cidr'])
        if address.network.num_addresses > 256:
            continue
        for ip in address.network.hosts():
            if ip != address.ip:
                targets.append((n['iface'], str(ip)))
    return list(dict.fromkeys(targets))[:254]


def collect(probe=False):
    networks = []
    interfaces = re.findall(r'^\s*Interface (\S+)', run(['iw', 'dev']), re.M)
    addresses = json.loads(run(['ip', '-j', '-4', 'addr', 'show']))
    for iface in interfaces:
        link = run(['iw', 'dev', iface, 'link'])
        ap = re.search(r'Connected to ([0-9a-f:]{17})', link, re.I)
        if not ap:
            continue
        for entry in addresses:
            if entry['ifname'] != iface:
                continue
            for a in entry.get('addr_info', []):
                if a.get('family') != 'inet':
                    continue
                cidr = f"{a['local']}/{a['prefixlen']}"
                network = str(ipaddress.ip_interface(cidr).network)
                networks.append(dict(iface=iface, cidr=cidr, network=network,
                                     identity=f'{iface}|{ap[1]}|{network}'))
    message = '' if networks else 'Geen verbonden WiFi-interface met IPv4.'
    if probe:
        targets = probe_targets(networks)
        if not shutil.which('ping'):
            message = 'ping ontbreekt; alleen ARP/mDNS-cache.'
        elif targets:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(lambda t: run(['ping', '-n', '-I', t[0], '-c', '1', '-W', '1', t[1]], 2), targets))
            message = 'Subnetscan klaar; geen antwoord bewijst niet dat een apparaat uit staat.'
        else:
            message = 'Subnetscan overgeslagen: alleen subnetten van maximaal 256 adressen.'
    # Avahi is optional; returning cached service records does not prove liveness.
    mdns = run(['avahi-browse', '-a', '-r', '-t', '-p'], 3) if networks and shutil.which('avahi-browse') else ''
    neighbors = json.loads(run(['ip', '-j', '-4', 'neigh', 'show']))
    candidates = []
    for n in neighbors:
        for net in networks:
            if n.get('dev') == net['iface'] and ipaddress.ip_address(n['dst']) in ipaddress.ip_network(net['network']):
                candidates.append(n['dst'])
    # NSS may supply reverse-DNS / DHCP names. Never let DNS stall the panel.
    def resolve(ip):
        fields = run(['getent', 'hosts', ip], 0.5).split()
        return ip, fields[1][:120] if len(fields) > 1 else ''
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        names = dict(pool.map(resolve, sorted(set(candidates))[:64]))
    # Discard a snapshot if association changed while probing/resolving.
    for net in networks:
        if 'Connected to ' + net['identity'].split('|')[1] not in run(['iw', 'dev', net['iface'], 'link']):
            return dict(networks=[], neighbors=[], mdns='', names={}, message='WiFi gewijzigd; volgende meting afwachten.')
    return dict(networks=networks, neighbors=neighbors, mdns=mdns, names=names, message=message)


if __name__ == '__main__':
    try:
        print(json.dumps(collect('--probe' in sys.argv)))
    except (RuntimeError, ValueError, OSError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
