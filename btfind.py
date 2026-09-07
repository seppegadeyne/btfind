#!/usr/bin/env python3
"""
btfind — Bluetooth-apparaat vinder voor Omarchy (curses TUI)

Scenario: apparaat (bv. smartwatch) verloren in huis maar nog aan.
  1. Start btfind -> scant continu naar Bluetooth LE-apparaten
  2. Selecteer het apparaat in de lijst
  3. Signaalsterkte-monitor: sterker signaal = dichterbij

Gebruik:
  btfind                          scan + lijst
  btfind --monitor AA:BB:CC:DD:EE:FF   direct volgen

Vereisten: python3 (stdlib), bluetoothctl (bluez-utils), actieve bluetooth-adapter.
Geen root nodig.
"""

import curses
import os
import re
import select
import subprocess
import sys
import time
from collections import deque

os.environ.setdefault("ESCDELAY", "25")

RSSI_MIN = -100.0
RSSI_MAX = -35.0
STALE_AFTER = 30          # sec zonder advertentie -> apparaat 'oud' in lijst
NO_SIGNAL_AFTER = 5       # sec zonder advertentie -> monitor waarschuwt
WINDOW_SORT = 15          # venster (sec) voor gemiddelde in de lijst
GRAPH_SPAN = 90           # sec geschiedenis in monitor-graaf
EMA_ALPHA = 0.35          # gladstrijken van 'huidig' signaal

QUALITY = [
    (-55, "ZEER DICHTBIJ", "~< 2 m"),
    (-65, "DICHTBIJ", "~2-4 m"),
    (-75, "ZELFDE RUIMTE", "~4-8 m"),
    (-85, "NABIJ", "andere kamer"),
    (-101, "VER / ZWAK", "grote afstand"),
]

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
DEV_RE = re.compile(r"\[(?:NEW|CHG)\] Device ([0-9A-Fa-f:]{17})\s*(.*)$")
LST_RE = re.compile(r"Device ([0-9A-Fa-f:]{17}) (.+)$")  # output van 'devices'-commando
RSSI_RE = re.compile(r"RSSI:\s*(?:0x[0-9a-fA-F]+\s*)?\(?(-?\d+)\)?")
RSSI_HEX_RE = re.compile(r"RSSI:\s*0x([0-9a-fA-F]+)")
NAME_RE = re.compile(r"^(?:Name|Alias):\s*(.+)$")
MACDASH_RE = re.compile(r"^[0-9A-Fa-f]{2}(-[0-9A-Fa-f]{2}){5}$")


def parse_line(line):
    """Parse een bluetoothctl-regel -> (mac, event) met event in {'rssi','name'} of None."""
    line = ANSI_RE.sub("", line.strip())  # bluetoothctl emit ANSI-kleurcodes
    m = DEV_RE.search(line)  # search: regel kan een "[bluetoothctl]> "-prompt-prefix bevatten
    if not m:
        # 'devices'-commando output: "Device MAC Naam" (zaait bekende apparaten)
        # search: ook hier kan een prompt-prefix voor staan; DEV_RE heeft
        # [NEW]/[CHG]-regels al afgevangen voordat we hier komen
        if "[DEL]" in line:
            return None
        lm = LST_RE.search(line)
        if lm:
            nm = lm.group(2).strip()
            if nm and nm.lower() != "(unknown)" and not MACDASH_RE.match(nm):
                return lm.group(1).upper(), ("name", nm[:32])
        return None
    mac, rest = m.group(1).upper(), m.group(2).strip()
    if rest.startswith("RSSI:"):
        r = RSSI_RE.search(rest)
        if r:
            v = int(r.group(1))
        else:
            # fallback: hex-only vorm (sommige bluez-versies), two's complement
            hx = RSSI_HEX_RE.search(rest)
            v = None
            if hx:
                v = int(hx.group(1), 16)
                if v >= 0x8000:
                    v -= 0x10000
        if v is not None and v < 0:  # 0 of onbekend negeren
            return mac, ("rssi", v)
    elif rest and not rest.startswith("("):
        # "[NEW] Device MAC Foo Bar" of "[CHG] Device MAC Name: Foo Bar"
        nm = NAME_RE.match(rest)
        if nm:
            nm = nm.group(1).strip()
        elif ":" in rest:
            return None  # TxPower/ManufacturerData/ServiceData-regs -> geen naam
        else:
            nm = rest
        nm = nm.split("\x1e")[0]
        if (nm and nm.lower() != "(unknown)"
                and not MACDASH_RE.match(nm)):  # "AA-BB-.." is geen echte naam
            return mac, ("name", nm)
    return None


class Dev:
    __slots__ = ("mac", "name", "samples", "first_seen")

    def __init__(self, mac):
        self.mac = mac
        self.name = None
        self.samples = deque(maxlen=2048)  # (t, rssi); genoeg voor 90s grafiek bij ~20 samples/s
        self.first_seen = time.time()

    def add(self, rssi):
        # downsample: max ~1 sample per 0,3 s per device (grafiek heeft kolommen
        # per ~1 s; hogere frequentie levert geen extra info maar vult de deque)
        now = time.time()
        if self.samples and now - self.samples[-1][0] < 0.3:
            # bewaar de sterkste van de twee (max-houding voorkomt dalen missen)
            if rssi > self.samples[-1][1]:
                self.samples[-1] = (self.samples[-1][0], rssi)
            return
        self.samples.append((now, rssi))

    def window(self, secs):
        t0 = time.time() - secs
        return [r for (t, r) in self.samples if t >= t0]

    def avg(self, secs=WINDOW_SORT):
        w = self.window(secs)
        return sum(w) / len(w) if w else None

    def latest(self):
        return self.samples[-1][1] if self.samples else None

    def age(self):
        return time.time() - self.samples[-1][0] if self.samples else None

    def label(self):
        n = self.name or ""
        return n if n else self.mac


class BtCtl:
    """Wrapper rond een langlopend `bluetoothctl`-proces (niet-blokkerend lezen)."""

    def __init__(self):
        self.p = subprocess.Popen(
            ["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0,
        )
        os.set_blocking(self.p.stdout.fileno(), False)
        self.buf = b""
        self.scanning = False
        self.full = False
        self.dead = False

    def send(self, cmd):
        try:
            self.p.stdin.write((cmd + "\n").encode())
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def start_scan(self, full=False):
        self.send("power on")
        # "scan le" = snel, alleen BLE (hoge samplefrequentie).
        # "scan on" = LE + klassiek (BR/EDR): vindt meer soorten toestellen,
        # maar de inquiry-cyclus verlaagt de LE-samplefrequentie sterk.
        self.send("scan on" if full else "scan le")
        self.full = full
        self.scanning = True
        # bekende/gepaarde apparaten zaaien: die verschijnen pas via [CHG]/[NEW]
        # als ze adverteren; met 'devices' staan ze direct (met naam) in de lijst
        self.send("devices")

    def stop_scan(self):
        self.send("scan off")
        self.scanning = False

    def poll(self):
        """Lees alles wat beschikbaar is; retourneer lijst events uit parse_line."""
        events = []
        if self.p.poll() is not None:
            self.dead = True
            return events
        r, _, _ = select.select([self.p.stdout], [], [], 0)
        if not r:
            return events
        try:
            chunk = os.read(self.p.stdout.fileno(), 65536)
        except OSError:
            return events
        if not chunk:
            return events
        self.buf += chunk
        while b"\n" in self.buf:
            raw, self.buf = self.buf.split(b"\n", 1)
            ev = parse_line(raw.decode("utf-8", errors="replace"))
            if ev:
                events.append(ev)
        return events

    def close(self):
        try:
            self.stop_scan()
            time.sleep(0.15)
            self.p.terminate()
            self.p.wait(timeout=2)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def ratio(rssi):
    return max(0.0, min(1.0, (rssi - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)))


def bar(rssi, width):
    n = int(round(ratio(rssi) * width))
    return "█" * n + "░" * (width - n)


def quality(rssi):
    for th, name, dist in QUALITY:
        if rssi >= th:
            return name, dist
    return QUALITY[-1][1], QUALITY[-1][2]


def fmt_age(secs):
    if secs is None:
        return "-"
    if secs < 1:
        return "nu"
    return f"{int(secs)}s"


class App:
    def __init__(self, stdscr, ctl, devs, monitor_mac=None):
        self.scr = stdscr
        self.ctl = ctl
        self.devs = devs
        self.mode = "monitor" if monitor_mac else "list"
        self.sel_mac = monitor_mac
        self.running = True
        self.status = ""
        # monitor-state per applicatie-sessie
        self.ema = None
        self.ema_hist = deque(maxlen=600)  # (t, ema)
        self.peak = None
        self.peak_t = None
        curses.curs_set(0)
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(6, curses.COLOR_WHITE, -1)  # dim via A_DIM

    # ---- helpers -------------------------------------------------------
    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w - 1:
            try:
                self.scr.addnstr(y, x, text, w - x - 1, attr)
            except curses.error:
                pass

    def dev_rows(self):
        now = time.time()
        rows = []
        for d in self.devs.values():
            if d.age() is not None and now - d.first_seen < 2 and not d.samples:
                continue
            a = d.avg()
            rows.append((a if a is not None else -999, d))
        rows.sort(key=lambda r: r[0], reverse=True)
        return [d for _, d in rows]

    def selected(self):
        return self.devs.get(self.sel_mac)

    def enter_monitor(self, mac):
        self.sel_mac = mac
        self.mode = "monitor"
        self.ema = None
        self.ema_hist.clear()
        self.peak = None
        self.peak_t = None
        if not self.ctl.scanning:
            self.ctl.start_scan()

    # ---- events --------------------------------------------------------
    def apply_events(self, events):
        for mac, ev in events:
            d = self.devs.get(mac)
            if d is None:
                d = self.devs[mac] = Dev(mac)
            if ev[0] == "rssi":
                d.add(ev[1])
                if self.mode == "monitor" and mac == self.sel_mac:
                    r = ev[1]
                    self.ema = r if self.ema is None else (
                        self.ema + EMA_ALPHA * (r - self.ema))
                    self.ema_hist.append((time.time(), self.ema))
                    if self.peak is None or r > self.peak:
                        new_peak = self.peak is None or r > self.peak + 2
                        self.peak, self.peak_t = r, time.time()
                        if new_peak:
                            try:
                                curses.beep()  # audio-cue: dichtstbijzijnde punt tot nu toe
                            except curses.error:
                                pass
            elif ev[0] == "name":
                nm = ev[1]
                # langere/expliciete naam vervangt korte advertentienaam
                if not d.name or len(nm) > len(d.name):
                    d.name = nm

    # ---- draw: lijst ----------------------------------------------------
    def draw_list(self):
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        scan = "AAN" if self.ctl.scanning else "UIT"
        mode = " · ALLE (LE+klassiek, trager)" if self.ctl.full else " · alleen LE (snel)"
        self.put(0, 0, f" btfind — apparaten in de buurt{' ' * 8}[scan: {scan}{mode}]", curses.A_REVERSE)
        self.put(1, 0, f"{'NAAM':<24} {'MAC':<19} {'RSSI':>5}  {'STERKTE':<14} {'GEM':>4}  GEZIEN", curses.A_DIM)
        rows = self.dev_rows()
        self._rows = rows
        max_rows = h - 4
        # scrollen: selectie blijft in beeld ook wanneer de lijst langer is
        idx = next((i for i, d in enumerate(rows) if d.mac == self.sel_mac), 0)
        if not hasattr(self, "scroll") or self._scroll_max != max_rows:
            self.scroll = 0
            self._scroll_max = max_rows
        if idx < self.scroll:
            self.scroll = idx
        elif idx >= self.scroll + max_rows:
            self.scroll = idx - max_rows + 1
        visible = rows[self.scroll:self.scroll + max_rows]
        for i, d in enumerate(visible):
            fresh = (d.age() or 1e9) < STALE_AFTER
            last = d.latest()
            a = d.avg() or -999
            attr = curses.A_DIM if not fresh else (
                curses.color_pair(1) if a >= -60 else
                curses.color_pair(2) if a >= -75 else curses.color_pair(3))
            if d.mac == self.sel_mac:
                attr |= curses.A_REVERSE
            name = (d.name or "(onbekend)")[:23]
            mac = d.mac
            rssi = f"{last}" if last is not None else "  - "
            b = bar(a if a > -900 else RSSI_MIN, 14)
            gem = f"{a:.0f}" if a > -900 else " - "
            self.put(2 + i, 0, f"{name:<24} {mac:<19} {rssi:>5}  {b} {gem:>4}  {fmt_age(d.age())}", attr)
        if not visible:
            y = 2
            for txt in (
                "",
                "  Scannen naar Bluetooth LE-apparaten...",
                "  Nog niets gevonden. Tip: veel horloges zenden alleen advertenties",
                "  uit als ze NIET verbonden zijn met een telefoon.",
            ):
                self.put(y, 0, txt)
                y += 1
        self.put(h - 2, 0, " ↑↓/jk: kiezen · Enter: signaal volgen · spatie: scan aan/uit · a: alle (LE+klassiek) · r: wissen · q: quit", curses.A_DIM)
        self.put(h - 1, 0, " " + self.status, curses.A_DIM)

    # ---- draw: monitor ----------------------------------------------------
    def draw_monitor(self):
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        d = self.selected()
        if d is None:
            self.put(0, 0, " Apparaat nog niet gezien — scan draait...", curses.A_REVERSE)
            self.put(2, 0, f" Zoeken naar {self.sel_mac} · q: afsluiten · Esc: terug")
            return
        scan = "AAN" if self.ctl.scanning else "UIT"
        scanbit = f"[scan: {scan}" + (" · ALLE (LE+klassiek, trager)" if self.ctl.full else " · alleen LE (snel)") + "]"
        deadbit = "  ⚠ BLUETOOTHCTL GESTOPT" if self.ctl.dead else ""
        self.put(0, 0, f" Signaalmonitor — {d.label()} {scanbit}{deadbit}", curses.A_REVERSE)
        age = d.age()
        dead = age is not None and age > NO_SIGNAL_AFTER
        cur = self.ema if self.ema is not None else d.latest()

        # trend: EMA nu t.o.v. ~8-10 s geleden
        trend = 0.0
        if self.ema is not None and len(self.ema_hist) > 2:
            t_ref = time.time() - 10
            past = next((e for (t, e) in self.ema_hist if t >= t_ref), None)
            if past is not None:
                trend = self.ema - past
        if trend > 1.5:
            tchar, ttxt, tattr = "▲", "signaal wordt STERKER → dichterbij", curses.color_pair(1) | curses.A_BOLD
        elif trend < -1.5:
            tchar, ttxt, tattr = "▼", "signaal wordt zwakker → verder weg", curses.color_pair(3) | curses.A_BOLD
        else:
            tchar, ttxt, tattr = "▬", "stabiel", curses.A_DIM

        qname, qdist = quality(cur) if cur is not None else ("-", "-")
        qattr = (curses.color_pair(1) if cur >= -60 else
                 curses.color_pair(2) if cur >= -75 else curses.color_pair(3)) if cur is not None else 0

        big = f"  {cur:+.0f} dBm  " if cur is not None else "  — geen signaal —  "
        self.put(2, 2, big, curses.A_REVERSE | curses.A_BOLD)
        self.put(2, 2 + len(big) + 2, f"{tchar} {ttxt} (trend 10s)", tattr)
        a5 = d.avg(5)
        a5txt = f"{a5:+.0f} dBm" if a5 is not None else "—"
        agetxt = fmt_age(age) if age is not None else "—"
        self.put(4, 2, f" gem. 5s: {a5txt}   laatste pakket: {agetxt} geleden")
        if self.peak is not None:
            self.put(5, 2, f" beste ooit deze sessie: {self.peak} dBm ({fmt_age(time.time() - self.peak_t)} geleden)")

        self.put(7, 2, f" kwaliteit: {qname} ({qdist})", qattr | curses.A_BOLD)
        self.put(8, 2, " " + bar(cur if cur is not None else RSSI_MIN, min(40, w - 6)), qattr)

        if self.ctl.dead:
            self.put(h - 3, 2, " ⚠ bluetoothctl is gestopt (adapter/dbus-probleem?) — herstart btfind", curses.color_pair(3) | curses.A_BOLD)
        elif dead and self.ctl.scanning:
            self.put(9, 2, f" ⚠ geen signaal sinds {int(age)}s — loop rustig rond, signaal kan terugkomen", curses.color_pair(3) | curses.A_BOLD)

        # graaf: laatste GRAPH_SPAN sec, kolommen = tijd
        gh = 6
        gw = min(w - 6, 100)
        top = 11
        self.put(top - 1, 2, f" geschiedenis ({GRAPH_SPAN}s, links=oud rechts=nu):", curses.A_DIM)
        # kolomgrafiek: elke kolom = tijdsvak, hoogte = sterkste signaal daarin
        # (één pass over samples i.p.v. per kolom scannen)
        now = time.time()
        col_max = [0] * gw  # 0 = geen data, anders niveau 1..gh
        t_start = now - GRAPH_SPAN
        for t, r in d.samples:
            if t < t_start:
                continue
            i = int((t - t_start) / GRAPH_SPAN * gw)
            if 0 <= i < gw:
                lvl = max(1, int(round(ratio(r) * gh)))
                if lvl > col_max[i]:
                    col_max[i] = lvl
        levels = col_max
        for row in range(gh):  # row 0 = onderste rij
            y = top + gh - 1 - row
            # dBm-aslabel links
            dbm = RSSI_MIN + (RSSI_MAX - RSSI_MIN) * row / gh
            line = []
            for lvl in levels:
                if lvl == 0:
                    line.append("·" if row == 0 else " ")
                elif lvl > row:
                    line.append("█")
                else:
                    line.append(" ")
            attr = curses.color_pair(1) if row >= gh * 0.66 else (
                curses.color_pair(2) if row >= gh * 0.33 else curses.color_pair(3))
            self.put(y, 2, f"{dbm:5.0f} " + "".join(line), attr)
        self.put(top + gh, 2, "      " + "-" * gw, curses.A_DIM)
        self.put(top + gh + 1, 2, f"      zwak (-{abs(int(RSSI_MIN))}) ← {GRAPH_SPAN}s → nu → sterk (-{abs(int(RSSI_MAX))}) dBm", curses.A_DIM)

        foot = h - 2
        self.put(foot, 0, " loop door het huis en volg de trend: ▲ = warmer, ▼ = kouder · afstanden zijn indicatief", curses.A_DIM)
        self.put(foot + 1, 0, " Esc/b: terug naar lijst · spatie: scan aan/uit · a: alle (LE+klassiek) · q: afsluiten", curses.A_DIM)

    # ---- main loop --------------------------------------------------------
    def run(self):
        self.scr.timeout(150)
        self.scr.keypad(True)
        while self.running:
            events = self.ctl.poll()
            if events:
                self.apply_events(events)
            if self.mode == "list":
                self.draw_list()
            else:
                self.draw_monitor()
            self.scr.refresh()
            ch = self.scr.getch()
            if ch == curses.KEY_RESIZE:
                continue
            if ch in (ord("q"), ord("Q")):
                self.running = False
            elif self.mode == "list":
                rows = getattr(self, "_rows", [])
                if not rows:
                    idx = -1
                else:
                    idx = next((i for i, d in enumerate(rows) if d.mac == self.sel_mac), 0)
                if ch in (curses.KEY_UP, ord("k")) and rows:
                    idx = max(0, idx - 1)
                    self.sel_mac = rows[idx].mac
                elif ch in (curses.KEY_DOWN, ord("j")) and rows:
                    idx = min(len(rows) - 1, idx + 1)
                    self.sel_mac = rows[idx].mac
                elif ch in (curses.KEY_ENTER, 10, 13, ord("s"), ord("S")) and rows:
                    self.enter_monitor(rows[max(0, idx)].mac)
                elif ch == ord(" "):
                    if self.ctl.scanning:
                        self.ctl.stop_scan()
                        self.status = "scan gestopt"
                    else:
                        self.ctl.start_scan()
                        self.status = "scan gestart"
                elif ch in (ord("a"), ord("A")):
                    # schakel tussen alleen-LE (snel) en LE+klassiek (meer devices)
                    self.ctl.stop_scan()
                    self.ctl.start_scan(full=not self.ctl.full)
                    self.status = ("volledige scan (LE+klassiek) — vaker klassieke "
                                   "toestellen, tragere updates") if self.ctl.full else "snelle LE-scan"
                elif ch in (ord("r"), ord("R")):
                    self.devs.clear()
                    self.status = "lijst gewist"
            else:  # monitor
                if ch in (27, ord("b"), ord("B")):
                    self.mode = "list"
                elif ch == ord(" "):
                    if self.ctl.scanning:
                        self.ctl.stop_scan()
                    else:
                        self.ctl.start_scan()
                elif ch in (ord("a"), ord("A")):
                    self.ctl.stop_scan()
                    self.ctl.start_scan(full=not self.ctl.full)


def check_adapter():
    """True als er een bluetooth-controller is; anders foutmelding."""
    try:
        out = subprocess.run(["bluetoothctl", "list"], capture_output=True,
                             text=True, timeout=5).stdout
        return "Controller" in out
    except Exception:
        return False


def main():
    monitor_mac = None
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--monitor":
        monitor_mac = args[1].replace("-", ":").upper()
        if not re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}", monitor_mac):
            print(f"Ongeldig MAC-adres: {args[1]!r}")
            print("Verwacht formaat: AA:BB:CC:DD:EE:FF (of met streepjes)")
            sys.exit(1)
    elif args:
        print(__doc__)
        sys.exit(0)

    if not sys.stdout.isatty():
        print("btfind heeft een terminal nodig (interactieve curses-app).")
        print("Start het direct in je terminal: btfind")
        sys.exit(1)

    if not check_adapter():
        print("Geen bluetooth-controller gevonden.")
        print("Check: bluetoothctl list · rfkill list bluetooth · systemctl status bluetooth")
        sys.exit(1)

    ctl = BtCtl()
    ctl.start_scan()
    devs = {}
    if monitor_mac:
        devs[monitor_mac] = Dev(monitor_mac)

    def run(stdscr):
        curses.start_color()
        curses.use_default_colors()
        App(stdscr, ctl, devs, monitor_mac).run()

    try:
        curses.wrapper(run)
    finally:
        ctl.close()


if __name__ == "__main__":
    main()
