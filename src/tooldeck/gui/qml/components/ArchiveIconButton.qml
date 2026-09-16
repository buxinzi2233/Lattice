import QtQuick
import QtQuick.Controls
import ".."

Button {
    id: control

    property string iconName: "plus"
    property string kind: "neutral"
    property string tip: ""
    property string label: ""
    property bool showLabel: false
    property real symbolSize: 17

    implicitWidth: showLabel && label.length > 0 ? 86 : 38
    implicitHeight: 38
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: tip
    opacity: enabled ? 1 : 0.38
    transform: Translate {
        y: control.down ? 1 : 0
        Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
    }

    Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }

    readonly property bool darkSurface: kind === "dark" || kind === "darkDanger"
    readonly property color baseColor: {
        if (kind === "telemetry") return Theme.telemetry
        if (kind === "command") return Theme.command
        if (kind === "danger") return Theme.danger
        if (darkSurface) return Theme.inkRaised
        return Theme.paperRaised
    }
    readonly property color foreground: {
        if (!enabled) return Theme.faint
        if (kind === "darkDanger") return Theme.danger
        if (darkSurface) return Theme.mutedOnDark
        if (kind === "neutral") return Theme.text
        return Theme.white
    }
    readonly property color frameColor: {
        if (darkSurface) return Theme.lineDark
        if (kind === "telemetry") return Theme.telemetry
        if (kind === "command") return Theme.command
        if (kind === "danger") return Theme.danger
        return Theme.line
    }

    background: Rectangle {
        color: !control.enabled
            ? Theme.fog
            : control.down
                ? Qt.darker(control.baseColor, 1.18)
                : control.hovered
                    ? Qt.lighter(control.baseColor, control.darkSurface ? 1.32 : 1.08)
                    : control.baseColor
        border.width: Theme.lineWidth
        border.color: control.enabled ? control.frameColor : Theme.line
        radius: Theme.radiusSmall

        Behavior on color { ColorAnimation { duration: Theme.fast } }
        Behavior on border.color { ColorAnimation { duration: Theme.fast } }
    }

    contentItem: Item {
        Row {
            anchors.centerIn: parent
            spacing: control.showLabel && control.label.length > 0 ? 8 : 0

            VectorIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: control.iconName
                color: control.foreground
                width: control.symbolSize
                height: width
                strokeWidth: 1.8
            }
            Text {
                visible: control.showLabel && control.label.length > 0
                anchors.verticalCenter: parent.verticalCenter
                text: control.label
                color: control.foreground
                font.family: Theme.sans
                font.pixelSize: Theme.sp(10)
                font.weight: Font.Bold
            }
        }
    }

    ToolTip.visible: hovered && tip.length > 0
    ToolTip.text: tip
    ToolTip.delay: 420
}
