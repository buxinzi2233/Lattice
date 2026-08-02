import QtQuick
import ".."

Rectangle {
    id: toast

    property string message: ""
    property string kind: "success"

    function show(text, tone) {
        message = text
        kind = tone || "success"
        reveal.restart()
    }

    width: Math.min(520, Math.max(280, toastText.implicitWidth + 54))
    height: 44
    radius: 2
    color: Theme.ink
    border.width: 1
    border.color: kind === "warning" ? Theme.warning : kind === "error" ? Theme.danger : Theme.telemetry
    opacity: 0
    visible: opacity > 0

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 5
        color: toast.kind === "warning" ? Theme.warning : toast.kind === "error" ? Theme.danger : Theme.telemetry
    }

    Text {
        id: toastText
        anchors.left: parent.left
        anchors.leftMargin: 20
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: toast.message
        color: Theme.white
        font.family: Theme.sans
        font.pixelSize: Theme.sp(12)
        elide: Text.ElideRight
    }

    SequentialAnimation {
        id: reveal
        PropertyAction { target: toast; property: "visible"; value: true }
        ParallelAnimation {
            NumberAnimation { target: toast; property: "opacity"; from: 0; to: 1; duration: Theme.normal }
            NumberAnimation { target: toast; property: "y"; from: toast.parent ? toast.parent.height - 54 : 0; to: toast.parent ? toast.parent.height - 72 : 0; duration: Theme.normal; easing.type: Easing.OutCubic }
        }
        PauseAnimation { duration: 3400 }
        NumberAnimation { target: toast; property: "opacity"; to: 0; duration: Theme.normal }
    }
}
