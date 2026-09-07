# btfind — Bluetooth-apparaat vinder

Terminal-app (curses TUI) voor Omarchy om verloren Bluetooth-apparaten in huis
te lokaliseren via signaalsterkte (RSSI).

Typisch scenario: de smartwatch van je zoon ligt ergens in huis, staat nog aan,
maar niemand weet waar.

## Gebruik

    btfind

1. De app scant direct naar Bluetooth LE-apparaten in de buurt.
2. Kies met ↑/↓ (of j/k) het apparaat in de lijst (gesorteerd op signaalsterkte).
3. Druk Enter -> signaalmonitor: loop door het huis en volg de trend.
   - ▲ signaal wordt sterker -> je loopt er naartoe
   - ▼ signaal wordt zwakker -> je loopt er van weg
   - Grotere balk / hoger getal (dBm) = dichter bij

Direct een bekend MAC-adres volgen:

    btfind --monitor AA:BB:CC:DD:EE:FF

## Toetsen

Lijst:
  ↑/↓ of j/k   apparaat kiezen
  Enter / s    signaalmonitor openen
  spatie       scan aan/uit
  a            scanmodus wisselen: alleen LE (snel) <-> LE + klassiek
  r            lijst wissen
  q            afsluiten

Monitor:
  Esc / b      terug naar lijst
  spatie       scan aan/uit
  a            scanmodus wisselen (zie hierboven)
  q            afsluiten

## Scanmodi

- Alleen LE (standaard): hoge samplefrequentie, ideale live-monitor.
- ALLE (LE + klassiek, toets 'a'): vindt ook klassieke BR/EDR-toestellen
  (headsets, oudere apparaten), maar de inquiry-cyclus maakt de LE-updates
  duidelijk trager. Gebruik dit om een ontbrekend toestel te vinden, schakel
  daarna terug voor het volgen van het signaal.

## Vereisten

- python3 (alleen stdlib)
- bluez-utils (bluetoothctl)
- werkende bluetooth-adapter (geen root nodig)

## Installatie

```sh
git clone https://github.com/seppegadeyne/btfind.git ~/Projects/btfind
mkdir -p ~/.local/bin
chmod +x ~/Projects/btfind/btfind.py
ln -sfn ~/Projects/btfind/btfind.py ~/.local/bin/btfind
```

Zorg dat `~/.local/bin` in je `PATH` staat. De TUI werkt ook zonder Omarchy;
alleen de onderstaande topbar-plugin vereist Omarchy met Quickshell.

### Omarchy Quickshell-topbar

```sh
mkdir -p ~/.config/omarchy/plugins/btfind
cp ~/Projects/btfind/shell-plugin/{manifest.json,BtFind.qml,Model.js,wifi-scan.py} \
  ~/.config/omarchy/plugins/btfind/
```

Voeg in `~/.config/omarchy/shell.json` onder `bar.layout.right` één entry toe,
bijvoorbeeld direct vóór `{"id": "omarchy.tray"}`. Behoud alle andere entries:

```json
{"id": "btfind"}
```

Pas op de komma tussen array-items. Activeer en controleer daarna:

```sh
omarchy-restart-shell
omarchy-shell shell listPlugins | jq '.[] | select(.id == "btfind")'
```

Rechts verschijnt een Bluetooth-knop met tooltip **Bluetooth Finder**. Klikken
klapt een natief Omarchy-paneel open (zoals de bluetooth/audio/netwerk-panelen,
zelfde styling en klik-buitenom-sluiten) — geen los terminalvenster meer. Het
paneel toont een live apparatenlijst gesorteerd op signaalsterkte, met
kleurgecodeerde sterktebalken en trend (▲ sterker / ▼ zwakker / ◆ stabiel).
Enter opent de signaalmonitor met geschiedenis-graaf (laatste 90 s); loop door
het huis en volg de trend, net als in de TUI. Scannen start alleen zolang het
paneel open is en stopt automatisch bij sluiten; de plugin verandert zelf geen
adapterinstellingen. Onbekende apparaten krijgen een compacte naam
(`•` + laatste 5 tekens van het MAC); via `bluetoothctl info` worden namen
opgelost en kun je zelf een alias geven (Enter op een apparaat), bewaard in
`~/.config/omarchy/plugins/btfind/aliases.json`. Het icoon gebruikt dezelfde
Nerd Font-glyph als Omarchy's Bluetooth-paneel. Er is geen extra service of
Waybar nodig. Plugin-updates installeren: kopieer de vier pluginbestanden
opnieuw en herstart de shell.

De persoonlijke `shell.json` blijft lokaal en hoort niet in deze repository.
Een eventuele oudere launcher-entry kun je verwijderen:

```sh
rm -f ~/.local/share/applications/btfind.desktop
```

Verwijder voor het uitschakelen van de topbar-knop alleen de `btfind`-entry uit
`bar.layout.right` en voer `omarchy-restart-shell` uit.

## WiFi-apparaten in het paneel

Klik **WiFi** voor IPv4-apparaten in hetzelfde subnet als de verbonden
WiFi-interface. Dit is **netwerkaanwezigheid, geen afstandsmeter** en geen
volledige router-clientlijst: ook bekabelde apparaten kunnen verschijnen.

- Elke **20 seconden**, uitsluitend zolang het WiFi-paneel open is: `ip -j -4
  neigh` (ARP-cache), optioneel `avahi-browse -artp` (mDNS/DNS-SD) en begrensde
  `getent hosts`-resolutie (NSS, bijvoorbeeld reverse-DNS/DHCP-hostnames).
  Normaal worden geen subnetpings gestuurd; mDNS/DNS-resolutie kan wel
  netwerkverkeer veroorzaken. ARP zelf bevat geen hostnames.
- **Scan subnet** is expliciet opt-in: één ping per adres op direct verbonden
  IPv4-subnetten van maximaal 256 adressen, maximaal 254 doelen totaal,
  16 gelijktijdige processen met time-outs. Geen poortscan. Een ping veroorzaakt
  normale ARP-resolutie; een apparaat kan daardoor zichtbaar worden zelfs als
  het ICMP blokkeert. Gebruik dit alleen op netwerken die je mag scannen.
- Namen, IPv4-adres, MAC (of **MAC onbekend** bij alleen mDNS), eerste waarneming
  en laatste bevestiging worden getoond. Apparaten zonder hostname krijgen de
  fabrikantnaam uit de IEEE OUI-database (`/usr/share/hwdata/oui.txt`) als
  label, ook bij Bluetooth. **ONLINE** betekent dat de kernel de
  buur als `REACHABLE` kent, niet dat we het apparaat fysiek dichtbij meten.
  **ONBEKEND** is een onbevestigde cache/mDNS-vermelding (`STALE`, `DELAY`,
  `PROBE`, statische ARP). **OFFLINE?** betekent `FAILED` of meer dan 90 seconden
  zonder bevestiging; slaapstand, client-isolatie en filtering kunnen dezelfde
  uitkomst geven. Het vraagteken is bewust: afwezigheid is geen bewijs.
- `Laatst bevestigd` verandert niet door alleen een oude ARP/mDNS-vermelding.
  De kernel bepaalt hoe lang `REACHABLE` geldig blijft; tijden zijn lokale
  observaties, geen exacte verbindings- of pakket-tijdstempels.
- Geschiedenis is alleen in het geheugen, wordt bij een andere AP/subnet-context
  gewist en verdwijnt bij een shell-herstart. Dertig minuten niet meer in een
  snapshot waargenomen apparaten worden verwijderd. Roaming naar een andere
  BSSID start conservatief een nieuwe lijst. Een lopende meting mag bij sluiten
  nog afronden; daarna start geen nieuwe poll. Er loopt maximaal één meting.

Vereisten: `python3` (stdlib), `ip` (iproute2), `iw`; optioneel Avahi voor mDNS,
`getent` voor namen en `ping` (iputils) voor de subnetknop. Geen root, extra
Python/Node-packages, daemon of adapterinstellingen nodig. De plugin gebruikt
geen `nmcli` en werkt onafhankelijk van NetworkManager/systemd-networkd.
IPv6-only apparaten en andere VLANs/subnetten vallen buiten deze eerste versie.

### Waarom geen WiFi-afstand?

Een gewone managed WiFi-client ontvangt geen bruikbare RSSI-metingen van alle
andere clients via ARP/ping/mDNS. `iw dev <interface> station dump` kan in
clientmodus **wel** werken, maar toont normaal alleen het verbonden accesspoint;
die signaalsterkte zegt niets over de afstand tot een telefoon. In AP-modus ziet
het AP zijn eigen aangesloten stations. Router/AP-telemetrie kan eventueel
client-RSSI leveren (afstand tot het **AP**, niet tot deze laptop).
Monitor-mode/raw ARP-scans (`arp-scan`, privileged nmap discovery) vragen
extra privileges en/of adapterwijzigingen en zijn bewust niet geïmplementeerd.
Unprivileged nmap kan TCP-connect-discovery gebruiken, maar is hier niet nodig.
Ping-latentie wordt nooit als afstand gebruikt. Slapende telefoons, private
MAC-adressen en AP-client-isolatie kunnen detectie beperken.

### Tests en diagnose

```sh
node --test tests/*.test.cjs
python3 shell-plugin/wifi-scan.py          # alleen verzamelen/resolutie
python3 shell-plugin/wifi-scan.py --probe  # expliciete subnetpings
omarchy-shell btfind wifi
omarchy-shell btfind status
omarchy-shell btfind close
```

Parsing, samenvoegen en historie zitten in `Model.js`; `wifi-scan.py` verzamelt
begrensd systeeminformatie en voert de optionele probes uit. De Node-tests
vereisen alleen Node zelf; de collector-test gebruikt daarnaast Python stdlib.

## Tips bij zoeken

- Veel horloges/armbanden zenden alleen advertenties uit als ze NIET met een
  telefoon verbonden zijn. Zet bluetooth op de telefoon van je zoon uit, dan
  begint het horloge te zenden en vind je het terug.
- Afstanden zijn indicatief: -55 dBm is ~<2 m, -65 ~2-4 m, -75 zelfde ruimte,
  zwakker dan -85 waarschijnlijk een andere kamer.
- RSSI springt; kijk naar de trend en het gemiddelde (5s), niet naar één getal.
