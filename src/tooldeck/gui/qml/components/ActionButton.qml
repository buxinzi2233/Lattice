import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Button {
    id: control

    property string symbol: ""
    property string iconName: ""
    property string label: ""
    property string kind: "neutral"
    property string tip: ""
    property bool iconOnly: label.length === 0
    property int symbolSize: 17
    property real symbolYOffset: 0

    text: label
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    implicitHeight: 38
    implicitWidth: iconOnly ? 38 : Math.max(88, contentRow.implicitWidth + 26)
    Accessible.name: tip.length > 0 ? tip : label
    opacity: enabled ? 1 : 0.42
    transform: Translate {
        y: control.down ? 1 : 0
        Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
    }

    Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }

    readonly property color baseColor: {
        if (kind === "command") return Theme.command
        if (kind === "danger") return Theme.ink
        if (kind === "dark") return Theme.inkRaised
        return "transparent"
    }
    readonly property color textColor: kind === "neutral" ? Theme.text : Theme.white
    readonly property color borderColor: {
        if (kind === "command") return Theme.command
        if (kind === "danger" || kind === "dark") return Theme.ink
        return Theme.line
    }

    background: Rectangle {
        radius: Theme.radiusSmall
        color: !control.enabled
            ? Theme.fog
            : control.down
                ? (control.kind === "command" ? Theme.commandDark : Theme.lineDark)
                : control.hovered
                    ? (control.kind === "neutral" ? Theme.fog : Qt.lighter(control.baseColor, 1.12))
                    : control.baseColor
        border.width: Theme.lineWidth
        border.color: control.enabled ? control.borderColor : Theme.line

        Behavior on color { ColorAnimation { duration: Theme.fast } }
        Behavior on border.color { ColorAnimation { duration: Theme.fast } }
    }

    contentItem: Item {
        implicitWidth: contentRow.implicitWidth
        implicitHeight: Math.max(24, contentRow.implicitHeight)

        RowLayout {
            id: contentRow
            anchors.centerIn: parent
            spacing: control.label.length > 0 && (control.symbol.length > 0 || control.iconName.length > 0) ? 8 : 0

            Item {
                visible: control.iconName.length > 0 || control.symbol.length > 0
                implicitWidth: 24
                implicitHeight: 24
                Layout.alignment: Qt.AlignVCenter
                VectorIcon {
                    visible: control.iconName.length > 0
                    name: control.iconName
                    color: control.enabled ? control.textColor : Theme.faint
                    opticalY: control.symbolYOffset
                }
                Text {
                    anchors.centerIn: parent
                    visible: control.iconName.length === 0 && control.symbol.length > 0
                    text: control.symbol
                    color: control.enabled ? control.textColor : Theme.faint
                    font.family: Theme.mono
                    font.pixelSize: control.symbolSize
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Text {
                visible: control.label.length > 0
                text: control.label
                color: control.enabled ? control.textColor : Theme.faint
                font.family: Theme.sans
                font.pixelSize: Theme.sp(12)
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.alignment: Qt.AlignVCenter
            }
        }
    }

    ToolTip.visible: hovered && tip.length > 0
    ToolTip.text: tip
    ToolTip.delay: 450
}
