import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Popup {
    id: popup

    property string code: ""
    property string heading: "确认指令"
    property string message: ""
    property string confirmLabel: "确认"
    property string tone: "command"
    signal confirmed(string code)

    function ask(nextCode, nextHeading, nextMessage, nextLabel, nextTone) {
        code = nextCode
        heading = nextHeading
        message = nextMessage
        confirmLabel = nextLabel || "确认"
        tone = nextTone || "command"
        open()
    }

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(480, parent.width - 48)
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape

    Overlay.modal: Rectangle { color: "#990d100e" }

    background: Rectangle {
        color: Theme.paperRaised
        border.width: 1
        border.color: Theme.ink
        radius: 2
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 7
            color: popup.tone === "danger" ? Theme.danger : Theme.command
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: 24
            spacing: 13

            Text {
                text: "COMMAND AUTHORIZATION"
                color: Theme.command
                font.family: Theme.mono
                font.pixelSize: Theme.sp(9)
                font.weight: Font.Bold
            }

            Text {
                text: popup.heading
                color: Theme.text
                font.family: Theme.condensed
                font.pixelSize: Theme.sp(24)
                font.weight: Font.Bold
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }

            Text {
                text: popup.message
                color: Theme.muted
                font.family: Theme.sans
                font.pixelSize: Theme.sp(13)
                lineHeight: 1.35
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Item { Layout.fillWidth: true }
                ActionButton { label: "取消"; onClicked: popup.close() }
                ActionButton {
                    label: popup.confirmLabel
                    kind: popup.tone === "danger" ? "danger" : "command"
                    onClicked: {
                        popup.close()
                        popup.confirmed(popup.code)
                    }
                }
            }
        }
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.normal }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.normal; easing.type: Easing.OutCubic }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fast } }
}
