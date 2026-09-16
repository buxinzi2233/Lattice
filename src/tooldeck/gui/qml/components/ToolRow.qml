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
            id: selectionRail
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 2
            color: control.stateColor
            opacity: control.selected ? 0 : 1

            Behavior on color { ColorAnimation { duration: Theme.normal } }
            Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 4
            color: Theme.command
            opacity: control.selected ? 1 : 0
            transform: Scale {
                origin.x: 0
                origin.y: selectionRail.height / 2
                xScale: 1
                yScale: control.selected ? 1 : 0.55
                Behavior on yScale { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeEnter } }
            }

            Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
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
        transform: Translate {
            x: control.selected ? 2 : control.hovered ? 1 : 0
            Behavior on x { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeStandard } }
        }

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
            onTextChanged: statePulse.restart()
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
            text: control.toolState === "running" ? control.uptimeText : control.toolState === "starting" ? "STARTING" : control.toolState === "unready" ? "TIMEOUT" : control.toolState === "stopping" ? "STOPPING" : "STANDBY"
            color: Theme.faint
            font.family: Theme.mono
            font.pixelSize: Theme.sp(9)
        }
    }

    SequentialAnimation {
        id: statePulse
        NumberAnimation { target: stateText; property: "opacity"; from: 0.48; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
    }
}
