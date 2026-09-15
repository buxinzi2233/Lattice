pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: cell

    property string label: "CPU / PROCESSOR"
    property string valueText: "--"
    property string detailText: ""
    property real percent: -1

    readonly property real normalized: Math.max(0, Math.min(1, percent < 0 ? 0 : percent / 100))
    property real displayedNormalized: normalized

    Behavior on displayedNormalized { NumberAnimation { duration: Theme.slow; easing.type: Theme.easeStandard } }

    implicitWidth: 144
    implicitHeight: 74

    Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: Theme.line }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 10
        anchors.topMargin: 8
        anchors.bottomMargin: 8
        spacing: 8

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1

            Text {
                Layout.fillWidth: true
                text: cell.label
                color: Theme.muted
                font.family: Theme.mono
                font.pixelSize: Theme.sp(7)
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                id: metricValue
                Layout.fillWidth: true
                text: cell.valueText
                color: Theme.text
                font.family: Theme.mono
                font.pixelSize: Theme.sp(17)
                font.weight: Font.Bold
                elide: Text.ElideRight
                onTextChanged: valuePulse.restart()
            }
            Text {
                Layout.fillWidth: true
                text: cell.detailText
                color: Theme.faint
                font.family: Theme.mono
                font.pixelSize: Theme.sp(7)
                elide: Text.ElideRight
            }
        }

        Row {
            Layout.preferredWidth: 39
            Layout.preferredHeight: 40
            Layout.alignment: Qt.AlignVCenter
            spacing: 2

            Repeater {
                model: 7
                Rectangle {
                    required property int index
                    anchors.bottom: parent.bottom
                    width: 3
                    height: 8 + index * 4
                    color: cell.displayedNormalized >= (index + 1) / 7 ? Theme.telemetry : Theme.line

                    Behavior on color { ColorAnimation { duration: Theme.normal } }
                }
            }
        }
    }

    SequentialAnimation {
        id: valuePulse
        NumberAnimation { target: metricValue; property: "opacity"; from: 0.58; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
    }
}
