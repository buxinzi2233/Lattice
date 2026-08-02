import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Item {
    id: startup
    required property var bridge
    property bool previewMode: false
    property bool showing: false
    signal closed()

    function show(preview) {
        previewMode = Boolean(preview)
        progressBar.width = 0
        showing = true
        visible = true
        opacity = 1
        progress.restart()
    }

    function dismiss() {
        if (!visible)
            return
        progress.stop()
        visible = false
        showing = false
        if (!previewMode)
            bridge.markStartupShown()
        closed()
    }

    anchors.fill: parent
    visible: false
    opacity: 0
    z: 900

    Rectangle { anchors.fill: parent; color: Theme.ink }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 24
        color: "transparent"
        border.width: 1
        border.color: Theme.telemetryDark
    }

    Repeater {
        model: 18
        Rectangle {
            x: 24 + index * (startup.width - 48) / 18
            y: 24
            width: 1
            height: startup.height - 48
            color: index % 3 === 0 ? "#1d4f4a" : "#17211f"
            opacity: 0.52
        }
    }

    Rectangle {
        id: panel
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 72
        anchors.rightMargin: 72
        height: Math.min(460, parent.height - 120)
        color: "#121815"
        border.width: 1
        border.color: Theme.lineDark

        RowLayout {
            anchors.fill: parent
            anchors.margins: 30
            spacing: 24

            Item {
                Layout.preferredWidth: Math.min(420, panel.width * 0.42)
                Layout.fillHeight: true

                Rectangle { anchors.fill: parent; color: "#0f1311"; border.width: 1; border.color: Theme.telemetryDark }
                Image {
                    id: officialImage
                    anchors.fill: parent
                    anchors.margins: 1
                    source: bridge.startupImageUrl
                    asynchronous: true
                    cache: false
                    fillMode: Image.PreserveAspectCrop
                    smooth: true
                    opacity: 0.82
                    visible: status === Image.Ready
                }
                Canvas {
                    anchors.fill: parent
                    visible: !officialImage.visible
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        ctx.fillStyle = "#15201d"
                        for (var y = 0; y < height; y += 18)
                            ctx.fillRect(0, y, width, 1)
                        ctx.strokeStyle = "#16b8a6"
                        ctx.lineWidth = 2
                        ctx.beginPath()
                        ctx.moveTo(width * 0.5, 32)
                        ctx.lineTo(width - 42, height * 0.5)
                        ctx.lineTo(width * 0.5, height - 32)
                        ctx.lineTo(42, height * 0.5)
                        ctx.closePath()
                        ctx.stroke()
                        ctx.beginPath()
                        ctx.moveTo(width * 0.5, 62)
                        ctx.lineTo(width - 78, height * 0.5)
                        ctx.lineTo(width * 0.5, height - 62)
                        ctx.lineTo(78, height * 0.5)
                        ctx.closePath()
                        ctx.stroke()
                    }
                }
                Text {
                    anchors.centerIn: parent
                    text: "RHINE\nLAB"
                    color: Theme.white
                    font.family: Theme.condensed
                    font.pixelSize: Theme.sp(42)
                    font.weight: Font.Black
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 0.82
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

                Text { text: "RHINE LIFE SAFETY PROTOCOL"; color: Theme.telemetry; font.family: Theme.mono; font.pixelSize: Theme.sp(10); font.weight: Font.Bold }
                Text { text: bridge.startupContent.character || "LATTICE"; color: Theme.white; font.family: Theme.condensed; font.pixelSize: Theme.sp(42); font.weight: Font.Black; Layout.fillWidth: true; elide: Text.ElideRight }
                Text { text: bridge.startupContent.faction || "莱茵生命"; color: Theme.mutedOnDark; font.family: Theme.mono; font.pixelSize: Theme.sp(11); Layout.fillWidth: true }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.lineDark }
                Text { text: bridge.startupContent.quote_zh || bridge.startupContent.quote || "LOCAL SYSTEM READY"; color: Theme.white; font.family: Theme.sans; font.pixelSize: Theme.sp(19); wrapMode: Text.Wrap; Layout.fillWidth: true }
                Text { text: bridge.startupContent.quote_en || "Local system ready"; color: Theme.mutedOnDark; font.family: Theme.sans; font.pixelSize: Theme.sp(12); wrapMode: Text.Wrap; Layout.fillWidth: true }
                Item { Layout.fillHeight: true }
                Text { text: "CONTENT SOURCE / " + (bridge.startupContent.source_url || "OFFLINE FALLBACK"); color: Theme.faintOnDark; font.family: Theme.mono; font.pixelSize: Theme.sp(8); elide: Text.ElideMiddle; Layout.fillWidth: true }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 4
                    color: Theme.lineDark
                    Rectangle { id: progressBar; width: 0; height: parent.height; color: Theme.command }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "LATTICE 0.2.0 / BOOTSTRAP"; color: Theme.telemetry; font.family: Theme.mono; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                    Item { Layout.fillWidth: true }
                    ActionButton { label: "跳过"; kind: "dark"; onClicked: startup.dismiss() }
                }
            }
        }
    }

    Rectangle {
        width: parent.width
        height: 2
        y: 24
        color: Theme.telemetry
        opacity: 0.42
        SequentialAnimation on x {
            loops: Animation.Infinite
            NumberAnimation { from: -startup.width; to: startup.width; duration: 1400 }
        }
    }

    NumberAnimation {
        id: progress
        target: progressBar
        property: "width"
        from: 0
        to: progressBar.parent ? progressBar.parent.width : 0
        duration: 4200
        easing.type: Easing.InOutCubic
        onFinished: startup.dismiss()
    }
}
