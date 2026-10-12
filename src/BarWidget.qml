import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "hnry047.netmount"
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("nas_app.py").toString().replace(/^file:\/\//, ""))
  property int mountedCount: 0
  property int savedCount: 0
  property bool statusError: false
  // The manager is an external GTK window, so the bar can't see it opening.
  // Mirror its mapped state into the bar's popout so the open-panel line shows.
  readonly property bool managerOpen: ToplevelManager.toplevels.values.some(function(t) {
    return t && (t.appId === "omarchy-netmount" || t.appId === "nas_app.py")
  })
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function syncPopout() {
    if (!root.bar) return
    if (root.managerOpen) root.bar.requestPopout(root)
    else root.bar.releasePopout(root)
  }

  onManagerOpenChanged: syncPopout()
  onBarChanged: syncPopout()

  function refresh() {
    if (!statusProcess.running) statusProcess.running = true
  }

  WidgetButton {
    id: button
    bar: root.bar
    text: "󰒍"
    foreground: root.bar ? (root.mountedCount > 0 ? root.bar.barForeground : Qt.darker(root.bar.barForeground, 1.5)) : Color.foreground
    tooltipText: root.statusError ? "Netmount · status unavailable · click to manage"
      : "Netmount · " + root.mountedCount + " mounted · " + root.savedCount + " saved · click to manage"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) Quickshell.execDetached(["/usr/bin/python3", root.helperPath, "--bar-position", root.bar ? root.bar.position : "top", "--bar-size", String(root.bar ? root.bar.barSize : 28)])
      else root.refresh()
    }
  }

  Component.onCompleted: managerProcess.running = true

  // Keep GTK ready, like shell-native panels that are already loaded on click.
  Process {
    id: managerProcess
    command: ["/usr/bin/python3", root.helperPath, "--preload"]
  }

  Process {
    id: statusProcess
    command: ["/usr/bin/python3", root.helperPath, "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var state = JSON.parse(text)
          root.mountedCount = state.mounted || 0
          root.savedCount = state.saved || 0
          root.statusError = state.error === true
        } catch (e) {
          root.statusError = true
        }
      }
    }
    onExited: function(exitCode) {
      if (exitCode !== 0) root.statusError = true
    }
  }

  Timer {
    interval: 5000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
}
