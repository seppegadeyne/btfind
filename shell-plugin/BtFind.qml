import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "btfind"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // Same Nerd Font Bluetooth glyph as Omarchy's Bluetooth panel.
    text: "󰂯"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    tooltipText: "Bluetooth Finder — zoek apparaten op signaalsterkte"
    onPressed: {
      if (root.bar) root.bar.run('omarchy-launch-floating-terminal-with-presentation "$HOME/.local/bin/btfind"')
    }
  }
}
