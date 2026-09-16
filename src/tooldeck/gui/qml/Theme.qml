pragma Singleton

import QtQuick

QtObject {
    property color ink: "#111412"
    property color inkRaised: "#1c211e"
    property color paper: "#f4f5f0"
    property color paperRaised: "#fafbf7"
    property color fog: "#e5e8e2"
    property color line: "#c9cdc6"
    property color lineDark: "#353b37"
    property color text: "#171b18"
    property color muted: "#4f5752"
    property color faint: "#68716b"
    property color mutedOnDark: "#b2bbb5"
    property color faintOnDark: "#929c95"
    property color white: "#f7f8f4"
    property color command: "#ef5b34"
    property color commandDark: "#c74424"
    property color telemetry: "#16b8a6"
    property color telemetryDark: "#087d74"
    property color warning: "#f0c928"
    property color danger: "#e14d34"
    property color consoleText: "#dbe4de"
    property color scrim: "#990d100e"
    property color scrimStrong: "#a60d100e"
    property color startupGrid: "#1d4f4a"
    property color startupGridDim: "#17211f"
    property color startupPanel: "#121815"
    property color startupCanvas: "#0f1311"
    property color startupCanvasFill: "#15201d"
    property real radiusSmall: 2
    property real radiusTiny: 1
    property int lineWidth: 1

    property string sans: "Fira Sans"
    property string condensed: "Fira Sans Condensed"
    property string mono: "JetBrainsMono Nerd Font"

    property real fontScale: 1.0

    function sp(size) {
        return Math.max(1, Math.round(size * fontScale))
    }

    function stateColor(state) {
        if (state === "running")
            return telemetry
        if (state === "starting" || state === "stopping")
            return warning
        if (state === "unready" || state === "exited" || state === "error")
            return danger
        return faint
    }

    function applyTokens(tokens) {
        if (!tokens)
            return
        ink = tokens.ink
        inkRaised = tokens.inkRaised
        paper = tokens.paper
        paperRaised = tokens.paperRaised
        fog = tokens.fog
        line = tokens.line
        lineDark = tokens.lineDark
        text = tokens.text
        muted = tokens.muted
        faint = tokens.faint
        mutedOnDark = tokens.mutedOnDark
        faintOnDark = tokens.faintOnDark
        white = tokens.white
        command = tokens.command
        commandDark = tokens.commandDark
        telemetry = tokens.telemetry
        telemetryDark = tokens.telemetryDark
        warning = tokens.warning
        danger = tokens.danger
        consoleText = tokens.consoleText
        scrim = tokens.scrim
        scrimStrong = tokens.scrimStrong
        startupGrid = tokens.startupGrid
        startupGridDim = tokens.startupGridDim
        startupPanel = tokens.startupPanel
        startupCanvas = tokens.startupCanvas
        startupCanvasFill = tokens.startupCanvasFill
        sans = tokens.sans
        condensed = tokens.condensed
        mono = tokens.mono
        radiusSmall = tokens.radiusSmall
        radiusTiny = tokens.radiusTiny
        lineWidth = tokens.lineWidth
        fast = tokens.fast
        normal = tokens.normal
        slow = tokens.slow
    }

    property int fast: 110
    property int normal: 190
    property int slow: 420

    // Motion semantics stay shared across theme packs while durations remain theme-owned.
    readonly property int easeStandard: Easing.OutCubic
    readonly property int easeEnter: Easing.OutQuart
    readonly property int easeExit: Easing.InCubic
    readonly property int easeAmbient: Easing.InOutSine
    readonly property real shiftSmall: 6
    readonly property real shiftMedium: 12
}
