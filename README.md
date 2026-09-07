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
cp ~/Projects/btfind/shell-plugin/manifest.json ~/Projects/btfind/shell-plugin/BtFind.qml \
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
opent btfind via `omarchy-launch-floating-terminal-with-presentation` en de
symlink `~/.local/bin/btfind`. De knop scant niet op de achtergrond en verandert
zelf geen adapterinstellingen; de TUI start de scan zodra je haar opent.
Het icoon gebruikt dezelfde Nerd Font-glyph als Omarchy's Bluetooth-paneel.
Er is geen extra service of Waybar nodig. Plugin-updates installeren: kopieer
de twee pluginbestanden opnieuw en herstart de shell.

De persoonlijke `shell.json` blijft lokaal en hoort niet in deze repository.
Een eventuele oudere launcher-entry kun je verwijderen:

```sh
rm -f ~/.local/share/applications/btfind.desktop
```

Verwijder voor het uitschakelen van de topbar-knop alleen de `btfind`-entry uit
`bar.layout.right` en voer `omarchy-restart-shell` uit.

## Tips bij zoeken

- Veel horloges/armbanden zenden alleen advertenties uit als ze NIET met een
  telefoon verbonden zijn. Zet bluetooth op de telefoon van je zoon uit, dan
  begint het horloge te zenden en vind je het terug.
- Afstanden zijn indicatief: -55 dBm is ~<2 m, -65 ~2-4 m, -75 zelfde ruimte,
  zwakker dan -85 waarschijnlijk een andere kamer.
- RSSI springt; kijk naar de trend en het gemiddelde (5s), niet naar één getal.
