import QtQuick
import QtQuick.Controls
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
    id: root
    moduleName: "btfind"
    ipcTarget: "btfind"
    manageIpc: false
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    property bool wifiMode: false
    property var wifiDevices: ({})
    property var wifiRows: []
    property string wifiMessage: ""
    property string wifiNetwork: ""
    property string wifiOutput: ""
    function pollWifi(probe) {
        if (!opened || !wifiMode || wifiScan.running) return;
        wifiMessage = ""; wifiOutput = "";
        wifiScan.command = ["python3", Qt.resolvedUrl("wifi-scan.py").toString().replace(/^file:\/\//, "")];
        if (probe) wifiScan.command = wifiScan.command.concat(["--probe"]);
        wifiScan.running = true;
    }
    function showWifi(value) {
        wifiMode = value; selectedMac = "";
        if (value) { stopScan(); pollWifi(false); }
        else startScan();
    }
    function wifiTime(value) { return value === null ? "niet bevestigd" : Qt.formatDateTime(new Date(value), "HH:mm:ss"); }
    property var devices: ({})
    property var aliases: ({})
    property var rows: []
    property var resolveQueue: []
    property string resolving: ""
    property var vendorQueue: []
    property string vendorMac: ""
    property var vendors: ({})
    property string selectedMac: ""
    property string cursorMac: ""
    property bool scanning: false
    property bool stopping: false
    property bool aliasReady: false
    property string message: ""
    property double now: Date.now()
    readonly property var selected: rows.find(function(d) { return d.mac === selectedMac; }) || null
    readonly property color foreground: Color.popups.text
    readonly property string family: bar ? bar.fontFamily : "monospace"

    function refresh() { now = Date.now(); rows = Model.rows(devices, aliases, now, vendors); }
    function ingest(line) {
        var plain = Model.clean(line);
        if (/Failed|No default controller|not available|NotReady|NotPowered/i.test(plain)) message = plain.slice(-180);
        var event = Model.parseLine(line);
        if (!event || event.removed) return;
        if (!devices[event.mac]) { resolveQueue.push(event.mac); vendorQueue.push(event.mac); }
        Model.update(devices, event, Date.now());
    }
    function startScan() {
        if (!opened || wifiMode || stopping || scan.running) return;
        message = ""; scanning = true; scan.running = true;
    }
    function stopScan() {
        scanning = false;
        if (!scan.running || stopping) return;
        stopping = true;
        // Same BlueZ client releases its own discovery session; never a global stop.
        scan.write("scan off\nquit\n");
        stopTimeout.restart();
        resolveQueue = [];
        vendorQueue = [];
    }
    function toggleScan() { if (!wifiMode) scanning ? stopScan() : startScan(); }
    function selectDevice(mac) {
        if (!devices[mac]) return;
        selectedMac = mac; cursorMac = mac;
        aliasInput.text = aliases[mac] || "";
    }
    function saveAlias(mac, name) {
        if (!aliasReady || !/^[0-9A-F]{2}(:[0-9A-F]{2}){5}$/.test(mac)) return false;
        var next = Object.assign({}, aliases);
        name = String(name).trim().slice(0, 120);
        if (name) next[mac] = name; else delete next[mac];
        aliasFile.setText(JSON.stringify(next, null, 2) + "\n");
        aliases = next; refresh(); return true;
    }
    function moveCursor(delta) {
        var i = rows.findIndex(function(d) { return d.mac === cursorMac; });
        i = Math.max(0, Math.min(rows.length - 1, i + delta));
        if (rows[i]) { cursorMac = rows[i].mac; list.positionViewAtIndex(i, ListView.Contain); }
    }
    function signalColor(value) { return value === null ? Color.muted : value >= -60 ? "#8ec07c" : value >= -75 ? "#fabd2f" : "#fb4934"; }
    function dbm(value) { return value === null ? "—" : Math.round(value) + " dBm"; }

    onOpenedChanged: {
        if (opened) { aliasFile.reload(); if (wifiMode) pollWifi(false); else startScan(); }
        else stopScan();
    }
    Component.onDestruction: { if (scan.running) scan.write("scan off\nquit\n"); }

    Timer {
        interval: 20000; running: root.opened && root.wifiMode; repeat: true
        onTriggered: root.pollWifi(false)
    }
    Process {
        id: wifiScan
        environment: ({"LC_ALL":"C", "PYTHONDONTWRITEBYTECODE":"1"})
        stdout: StdioCollector { onStreamFinished: root.wifiOutput = text }
        stderr: StdioCollector { onStreamFinished: { if (text.trim()) root.wifiMessage = text.trim().slice(-180); } }
        onExited: function(code, status) {
            var snapshot = code === 0 ? Model.parseWifi(root.wifiOutput) : null;
            if (snapshot) {
                Model.updateWifi(root.wifiDevices, snapshot, Date.now());
                root.wifiNetwork = snapshot.networks.map(function(n) {return n.iface + " · " + n.network;}).join(" / ");
                root.wifiMessage = snapshot.message;
            } else root.wifiMessage = root.wifiMessage || "WiFi-meting mislukt; controleer python3, ip en iw.";
            root.wifiRows = Model.wifiRows(root.wifiDevices, Date.now());
        }
    }
    FileView {
        id: aliasFile
        path: Quickshell.env("HOME") + "/.config/omarchy/plugins/btfind/aliases.json"
        atomicWrites: true
        blockWrites: true
        printErrors: false
        onLoaded: {
            try {
                var data = JSON.parse(text());
                if (!data || Array.isArray(data) || typeof data !== "object") throw new Error("not an object");
                var valid = {};
                Object.keys(data).forEach(function(mac) {
                    if (/^[0-9A-F]{2}(:[0-9A-F]{2}){5}$/i.test(mac) && typeof data[mac] === "string") valid[mac.toUpperCase()] = data[mac];
                });
                root.aliases = valid; root.aliasReady = true; root.refresh();
            } catch (e) { root.aliasReady = false; root.message = "aliases.json ongeldig; herstel het bestand voordat je opslaat."; }
        }
        onLoadFailed: function(error) {
            root.aliasReady = error === FileViewError.FileNotFound;
            if (!root.aliasReady) root.message = "Kan aliases.json niet lezen.";
        }
        onSaveFailed: root.message = "Alias kon niet worden opgeslagen; controleer schrijfrechten."
    }
    Process {
        id: scan
        command: ["bluetoothctl"]
        environment: ({"LC_ALL":"C"})
        stdinEnabled: true
        onStarted: {
            if (root.scanning && root.opened) write("scan le\n");
            else { write("scan off\nquit\n"); root.stopping = true; stopTimeout.restart(); }
        }
        stdout: SplitParser { onRead: function(data) { root.ingest(data); } }
        stderr: SplitParser { onRead: function(data) { root.message = Model.clean(data).slice(-180); } }
        onExited: function(code, status) {
            stopTimeout.stop();
            var expected = root.stopping;
            root.stopping = false; root.scanning = false;
            if (!expected && root.opened) root.message = "Scan gestopt (" + code + "). Controleer Bluetooth en probeer opnieuw.";
        }
    }
    Timer { id: stopTimeout; interval: 1500; onTriggered: scan.running = false }
    Timer {
        interval: 500; running: root.opened; repeat: true
        onTriggered: {
            root.refresh();
            root.wifiRows = Model.wifiRows(root.wifiDevices, root.now);
            if (root.scanning && !info.running && root.resolveQueue.length) {
                root.resolving = root.resolveQueue.shift();
                info.command = ["bluetoothctl", "--timeout", "3", "info", root.resolving];
                info.running = true;
            }
            if (root.opened && !oui.running && root.vendorQueue.length) {
                root.vendorMac = root.vendorQueue.shift();
                var prefix = root.vendorMac.replace(/:/g, "").substring(0, 6);
                oui.command = ["grep", "-m", "1", "-E", "^" + prefix + "\\s+\\(base 16\\)", "/usr/share/hwdata/oui.txt"];
                oui.running = true;
            }
        }
    }
    Process {
        id: info
        environment: ({"LC_ALL":"C"})
        stdout: StdioCollector {
            onStreamFinished: {
                var name = Model.infoName(text, root.resolving);
                if (name && root.devices[root.resolving]) root.devices[root.resolving].name = name;
                root.refresh();
            }
        }
    }
    Process {
        id: oui
        environment: ({"LC_ALL":"C"})
        stdout: StdioCollector {
            onStreamFinished: {
                // "788A20     (base 16)\t\tUbiquiti Inc"
                var m = String(text).match(/[0-9A-F]{6}\s+\(base 16\)\s+(\S.*)/i);
                if (m && root.vendorMac) {
                    var next = Object.assign({}, root.vendors);
                    next[root.vendorMac] = m[1].trim().slice(0, 60);
                    root.vendors = next;
                }
            }
        }
    }
    IpcHandler {
        target: "btfind"
        function open(): void { root.open(); }
        function wifi(): void { root.open(); root.showWifi(true); }
        function bluetooth(): void { root.showWifi(false); }
        function probeWifi(): void { root.pollWifi(true); }
        function close(): void { root.close(); }
        function toggle(): void { root.toggle(); }
        function toggleScan(): void { root.toggleScan(); }
        function select(mac: string): void { root.selectDevice(mac.toUpperCase()); }
        function back(): void { root.selectedMac = ""; }
        function rename(mac: string, name: string): bool { return root.saveAlias(mac.toUpperCase(), name); }
        function status(): string {
            return JSON.stringify({opened:root.opened, scanning:root.scanning, processRunning:scan.running,
                wifiMode:root.wifiMode, wifiRunning:wifiScan.running, wifiMessage:root.wifiMessage, wifiNetwork:root.wifiNetwork, wifiDevices:root.wifiRows,
                deviceCount:root.rows.length, signalCount:root.rows.filter(function(d) {return d.rssi !== null;}).length,
                selected:root.selected, aliasReady:root.aliasReady, message:root.message,
                devices:root.rows.map(function(d) {return {mac:d.mac,name:d.label,rssi:d.rssi,average:d.average};})});
        }
    }
    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󰧿"
        slotSize: Style.bar.statusSlot
        fontSize: Style.font.caption
        tooltipText: "Bluetooth Finder — Bluetooth-signaal en WiFi-aanwezigheid"
        onPressed: root.toggle()
    }
    KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: keys
        contentWidth: fittedContentWidth(Style.space(420))
        contentHeight: fittedContentHeight(Style.space(490))
        PanelKeyCatcher {
            id: keys
            anchors.fill: parent
            onMoveRequested: function(dx, dy) { if (!root.wifiMode && !root.selectedMac && dy) root.moveCursor(dy); }
            onActivateRequested: { if (!root.wifiMode && !root.selectedMac) root.selectDevice(root.cursorMac); }
            onCloseRequested: { if (root.selectedMac) root.selectedMac = ""; else root.close(); }
            onTabRequested: function(direction) { root.switchPanel(direction); }
            onTextKey: function(text) { if (text === " ") root.toggleScan(); if (text === "b") root.selectedMac = ""; }
            Column {
                anchors.fill: parent
                spacing: Style.space(12)
                Item {
                    width: parent.width; height: Style.space(44)
                    Column {
                        width: parent.width - scanToggle.width - Style.space(12)
                        LabelText { text: root.wifiMode ? "WiFi-netwerk" : "Bluetooth Finder"; font.pixelSize: Style.font.title; font.bold: true }
                        LabelText { text: root.wifiMode ? (wifiScan.running ? "METING BEZIG…" : root.wifiRows.length + " APPARATEN · 20 S") : root.scanning ? "LIVE · " + root.rows.length + " APPARATEN" : "SCAN GEPAUZEERD"; font.pixelSize: Style.font.caption; color: Color.muted }
                    }
                    ToggleSwitch {
                        id: scanToggle
                        visible: !root.wifiMode
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        checked: root.scanning; foreground: root.foreground
                        onToggled: root.toggleScan()
                    }
                }
                Row {
                    spacing: Style.space(8)
                    ActionButton { text: "Bluetooth"; enabled: root.wifiMode; onClicked: root.showWifi(false) }
                    ActionButton { text: "WiFi"; enabled: !root.wifiMode; onClicked: root.showWifi(true) }
                    ActionButton { text: "Scan subnet"; visible: root.wifiMode; enabled: !wifiScan.running; onClicked: root.pollWifi(true) }
                }
                PanelSeparator { foreground: root.foreground }
                Column {
                    visible: root.wifiMode
                    width: parent.width; spacing: Style.space(4)
                    LabelText { width: parent.width; text: root.wifiNetwork; elide: Text.ElideRight; font.pixelSize: Style.font.caption }
                    LabelText { text: "Aanwezigheid, geen afstand · ook bekabelde apparaten"; font.pixelSize: Style.font.caption; color: Color.muted }
                    LabelText { width: parent.width; text: root.wifiMessage; visible: text !== ""; wrapMode: Text.Wrap; font.pixelSize: Style.font.caption }
                }
                Item {
                    visible: root.wifiMode
                    width: parent.width; height: Math.max(0, parent.height - y)
                    LabelText { width: parent.width; visible: !root.wifiRows.length; wrapMode: Text.Wrap; text: "Nog geen apparaten. Scan subnet zoekt extra IPv4-buren (alleen op een netwerk dat je mag scannen)." }
                    ListView {
                        id: wifiList
                        anchors.fill: parent; clip: true; model: root.wifiRows
                        spacing: Style.space(4)
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: CursorSurface {
                            required property var modelData
                            width: wifiList.width; height: Style.space(94)
                            foreground: root.foreground
                            Column {
                                anchors.fill: parent; anchors.margins: Style.space(8); spacing: Style.space(3)
                                Row {
                                    width: parent.width
                                    LabelText { width: parent.width - Style.space(95); text: modelData.label; elide: Text.ElideRight; font.bold: true }
                                    LabelText { width: Style.space(95); text: modelData.status; horizontalAlignment: Text.AlignRight; font.pixelSize: Style.font.caption; color: modelData.status === "ONLINE" ? Color.accent : Color.muted }
                                }
                                LabelText { width: parent.width; text: modelData.ip + (modelData.vendor ? " · " + modelData.vendor : "") + " · " + (modelData.mac || "MAC onbekend"); elide: Text.ElideRight; font.pixelSize: Style.font.caption; color: Color.muted }
                                LabelText { text: "Eerst gezien " + root.wifiTime(modelData.first); color: Color.muted; font.pixelSize: Style.font.caption }
                                LabelText { text: "Laatst bevestigd " + root.wifiTime(modelData.last); color: Color.muted; font.pixelSize: Style.font.caption }
                            }
                        }
                    }
                }
                LabelText {
                    visible: !root.wifiMode && root.message !== ""
                    width: parent.width; text: root.message; wrapMode: Text.Wrap
                    color: Color.urgent; font.pixelSize: Style.font.caption
                }
                Item {
                    width: parent.width
                    height: Math.max(0, parent.height - y)
                    visible: !root.wifiMode && !root.selectedMac
                    LabelText {
                        visible: root.rows.length === 0; width: parent.width
                        text: root.scanning ? "Luisteren naar apparaten…\nZet Bluetooth op de gekoppelde telefoon uit als je horloge niet verschijnt." : "Zet de scan aan om apparaten te zoeken."
                        wrapMode: Text.Wrap
                    }
                    ListView {
                        id: list
                        anchors.fill: parent; clip: true
                        model: root.rows
                        spacing: Style.space(4)
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: CursorSurface {
                            required property var modelData
                            width: list.width; height: Style.space(modelData.named || modelData.vendor ? 68 : 54)
                            hasCursor: root.cursorMac === modelData.mac
                            foreground: root.foreground
                            opacity: modelData.stale ? 0.55 : 1
                            Column {
                                anchors.fill: parent; anchors.margins: Style.space(8); spacing: Style.space(3)
                                Row {
                                    width: parent.width
                                    LabelText { width: parent.width - Style.space(90); text: modelData.label; font.bold: modelData.named; elide: Text.ElideRight }
                                    LabelText { width: Style.space(90); text: root.dbm(modelData.rssi); color: root.signalColor(modelData.rssi); horizontalAlignment: Text.AlignRight }
                                }
                                LabelText { visible: modelData.named || modelData.vendor; text: modelData.vendor ? (modelData.named ? modelData.vendor + " · " : "") + modelData.mac : modelData.mac; font.pixelSize: Style.font.caption; color: Color.muted }
                                SignalBar { width: parent.width; value: modelData.average }
                            }
                            MouseArea {
                                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onEntered: root.cursorMac = modelData.mac
                                onClicked: root.selectDevice(modelData.mac)
                            }
                        }
                    }
                }
                Column {
                    visible: !root.wifiMode && !!root.selectedMac
                    width: parent.width; spacing: Style.space(10)
                    ActionButton { text: "‹ Apparaten"; onClicked: root.selectedMac = "" }
                    LabelText { width: parent.width; text: root.selected ? root.selected.label : ""; elide: Text.ElideRight; font.bold: true; font.pixelSize: Style.font.title }
                    LabelText { text: root.selectedMac; color: Color.muted; font.pixelSize: Style.font.caption }
                    LabelText {
                        text: root.selected ? root.dbm(root.selected.ema) : "—"
                        font.pixelSize: Style.font.display
                        color: root.signalColor(root.selected ? root.selected.ema : null)
                    }
                    LabelText {
                        text: !root.scanning ? "GEPAUZEERD" : !root.selected || root.selected.stale ? "GEEN RECENT SIGNAAL" : root.selected.trend + " · " + Model.quality(root.selected.ema)
                        font.pixelSize: Style.font.caption
                    }
                    SignalBar { width: parent.width; value: root.selected ? root.selected.ema : null }
                    Canvas {
                        id: graph
                        width: parent.width; height: Style.space(80)
                        property var samples: root.selected ? root.selected.history : []
                        onSamplesChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d"); ctx.reset();
                            ctx.strokeStyle = Color.muted; ctx.lineWidth = 1;
                            for (var i=0; i<3; i++) { var y = i * (height-1)/2; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(width,y); ctx.stroke(); }
                            ctx.strokeStyle = Color.accent; ctx.lineWidth = 2; ctx.beginPath();
                            for (var j=0; j<samples.length; j++) {
                                var x = width * (1-(root.now-samples[j].t)/90000), sy = height * (1-Model.ratio(samples[j].ema));
                                if (j === 0 || samples[j].t-samples[j-1].t > 5000) ctx.moveTo(x,sy); else ctx.lineTo(x,sy);
                            }
                            ctx.stroke();
                        }
                    }
                    LabelText { text: "90 s geschiedenis · RSSI is geen afstandsmeter"; font.pixelSize: Style.font.caption; color: Color.muted }
                    Row {
                        width: parent.width; spacing: Style.space(8)
                        TextField {
                            id: aliasInput
                            width: parent.width - saveButton.width - parent.spacing
                            placeholderText: "Eigen naam (leeg = wissen)"; maximumLength: 120
                            color: root.foreground; placeholderTextColor: Color.muted
                            font.family: root.family; font.pixelSize: Style.font.body
                            selectByMouse: true
                            background: CursorSurface { bordered: true; hasCursor: aliasInput.activeFocus; foreground: root.foreground }
                            onAccepted: { root.saveAlias(root.selectedMac, text); keys.forceActiveFocus(); }
                            Keys.onEscapePressed: keys.forceActiveFocus()
                        }
                        ActionButton { id: saveButton; text: "Bewaar"; enabled: root.aliasReady; onClicked: { root.saveAlias(root.selectedMac, aliasInput.text); keys.forceActiveFocus(); } }
                    }
                }
            }
        }
    }
    component LabelText: Text {
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.family
        font.pixelSize: Style.font.body
    }
    component SignalBar: Rectangle {
        property var value: null
        height: Style.space(5); radius: height / 2
        color: Style.hoverFillFor(root.foreground, Color.accent)
        Rectangle { width: parent.width * Model.ratio(parent.value); height: parent.height; radius: height / 2; color: root.signalColor(parent.value) }
    }
    component ActionButton: Controls.Button {
        id: action
        contentItem: LabelText { text: action.text; horizontalAlignment: Text.AlignHCenter }
        background: CursorSurface { hasCursor: action.hovered || action.activeFocus; bordered: true; foreground: root.foreground }
    }
}
