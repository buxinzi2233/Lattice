pragma Singleton

import QtQuick

QtObject {
    readonly property color ink: "#111412"
    readonly property color inkRaised: "#1c211e"
    readonly property color paper: "#f4f5f0"
    readonly property color paperRaised: "#fafbf7"
    readonly property color fog: "#e5e8e2"
    readonly property color line: "#c9cdc6"
    readonly property color lineDark: "#353b37"
    readonly property color text: "#171b18"
    readonly property color muted: "#4f5752"
    readonly property color faint: "#68716b"
    readonly property color mutedOnDark: "#b2bbb5"
    readonly property color faintOnDark: "#929c95"
    readonly property color white: "#f7f8f4"
    readonly property color command: "#ef5b34"
    readonly property color commandDark: "#c74424"
    readonly property color telemetry: "#16b8a6"
    readonly property color telemetryDark: "#087d74"
    readonly property color warning: "#f0c928"
    readonly property color danger: "#e14d34"

    readonly property string sans: "Fira Sans"
    readonly property string condensed: "Fira Sans Condensed"
    readonly property string mono: "JetBrainsMono Nerd Font"

    property real fontScale: 1.0

    function sp(size) {
        return Math.max(1, Math.round(size * fontScale))
    }

    readonly property int fast: 110
    readonly property int normal: 190
    readonly property int slow: 420
}
