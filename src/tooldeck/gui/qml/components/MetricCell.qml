import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: control

    property string label: "CPU"
    property string valueText: "--"
    property string detailText: ""
    property real percent: -1
    readonly property bool compact: width < Theme.sp(110)

    implicitWidth: 170
    implicitHeight: 72
    clip: true

    Rectangle {
        width: 1
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: Theme.line
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 11
        anchors.bottomMargin: 10
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                text: control.compact && control.label === "MEMORY" ? "MEM" : control.label
                color: Theme.muted
                font.family: Theme.mono
                font.pixelSize: Theme.sp(10)
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                Layout.maximumWidth: Math.max(30, control.width * 0.46)
            }

            Text {
                text: control.valueText
                color: control.percent >= 0 ? Theme.text : Theme.faint
                font.family: Theme.mono
                font.pixelSize: Theme.sp(18)
                font.weight: Font.Bold
                fontSizeMode: Text.Fit
                minimumPixelSize: 10
                maximumLineCount: 1
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideRight
                Layout.fillWidth: true
                Layout.minimumWidth: 24
            }
        }

        Text {
            text: control.detailText.length > 0 ? control.detailText : control.compact ? "SAMPLE" : "SYSTEM SAMPLE"
            color: Theme.faint
            font.family: Theme.mono
            font.pixelSize: Theme.sp(9)
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            color: Theme.fog

            Rectangle {
                height: parent.height
                width: control.percent < 0 ? 0 : parent.width * Math.max(0, Math.min(100, control.percent)) / 100
                color: control.percent > 90 ? Theme.warning : Theme.telemetry

                Behavior on width { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
            }
        }
    }
}
