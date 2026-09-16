import QtQuick
import QtQuick.Controls
import ".."

Button {
    id: control

    property string symbol: ""
    property string iconName: ""
    property string tip: ""
    property bool active: false
    property int symbolSize: 18
    property real symbolYOffset: 0

    hoverEnabled: true
    implicitWidth: 44
    implicitHeight: 44
    padding: 0
    Accessible.name: tip
    opacity: enabled ? 1 : 0.42
    transform: Translate {
        y: control.down ? 1 : 0
        Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
    }

    Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }

    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.down
            ? Theme.command
            : control.active
                ? Theme.paper
                : control.hovered
                    ? Theme.lineDark
                    : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.fast } }

        Rectangle {
            id: activeRail
            width: 3
            height: parent.height
            anchors.left: parent.left
            color: Theme.command
            opacity: control.active ? 1 : 0
            transform: Scale {
                origin.x: 0
                origin.y: activeRail.height / 2
                xScale: 1
                yScale: control.active ? 1 : 0.45
                Behavior on yScale { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeEnter } }
            }

            Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
        }
    }

    contentItem: Item {
        implicitWidth: 44
        implicitHeight: 44

        VectorIcon {
            visible: control.iconName.length > 0
            name: control.iconName
            anchors.centerIn: parent
            color: control.active ? Theme.ink : Theme.white
            opticalY: control.symbolYOffset
            width: 24
            height: 24
        }
        Text {
            visible: control.iconName.length === 0 && control.symbol.length > 0
            anchors.centerIn: parent
            text: control.symbol
            color: control.active ? Theme.ink : Theme.white
            font.family: Theme.mono
            font.pixelSize: control.symbolSize
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    ToolTip.visible: hovered
    ToolTip.text: tip
    ToolTip.delay: 450
}
