import QtQuick
import QtQuick.Controls
import ".."

ItemDelegate {
    id: control

    property string toolId: ""
    property string toolName: ""
    property string toolCwd: ""
    property string toolState: "stopped"
    property string stateLabel: ""
    property color stateColor: Theme.faint
    property string pidText: "----"
    property string uptimeText: "--"
    property string sequenceText: "--"
    property string groupKey: ""
    property int toolIndex: 0
    property int groupToolCount: 0
    property bool selected: false

    width: ListView.view ? ListView.view.width : 280
    height: 86 + Math.max(0, Theme.sp(16) - 16) * 2
    padding: 0
    hoverEnabled: true

    background: Rectangle {
        color: control.selected
            ? Theme.paperRaised
            : control.hovered
                ? Qt.lighter(Theme.fog, 1.04)
                : "transparent"
        border.width: 0
        Behavior on color { ColorAnimation { duration: Theme.fast } }

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: control.selected ? 4 : 2
            color: control.selected ? Theme.command : control.stateColor
            Behavior on width { NumberAnimation { duration: Theme.fast } }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.line
        }
    }

    contentItem: Item {
        Text {
            id: sequence
            anchors.left: parent.left
            anchors.leftMargin: 17
            anchors.top: parent.top
            anchors.topMargin: 14
            text: control.sequenceText
            color: control.selected ? Theme.command : Theme.faint
            font.family: Theme.mono
            font.pixelSize: Theme.sp(10)
            font.weight: Font.Bold
        }

        VectorIcon {
            anchors.right: parent.right
            anchors.rightMargin: 13
            anchors.top: parent.top
            anchors.topMargin: 12
            name: "drag"
            color: control.selected ? Theme.command : Theme.faint
            width: 16
            height: 16
        }

        Text {
            id: nameText
            anchors.left: sequence.right
            anchors.leftMargin: 13
            anchors.right: stateText.left
            anchors.rightMargin: 10
            anchors.top: parent.top
            anchors.topMargin: 10
            text: control.toolName
            color: Theme.text
            font.family: Theme.condensed
            font.pixelSize: Theme.sp(16)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        Text {
            id: stateText
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.verticalCenter: nameText.verticalCenter
            text: control.stateLabel
            color: control.stateColor
            font.family: Theme.sans
            font.pixelSize: Theme.sp(10)
            font.weight: Font.DemiBold
        }

        Text {
            anchors.left: nameText.left
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.top: nameText.bottom
            anchors.topMargin: 4
            text: control.toolId + "  ·  " + control.toolCwd
            color: Theme.muted
            font.family: Theme.mono
            font.pixelSize: Theme.sp(9)
            elide: Text.ElideMiddle
        }

        Text {
            anchors.left: nameText.left
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 11
            text: "PID " + control.pidText
            color: Theme.faint
            font.family: Theme.mono
            font.pixelSize: Theme.sp(9)
        }

        Text {
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 11
            text: control.toolState === "running" ? control.uptimeText : "STANDBY"
            color: Theme.faint
            font.family: Theme.mono
            font.pixelSize: Theme.sp(9)
        }
    }
}
