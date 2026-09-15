import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Item {
    id: row
    property string groupName: ""
    property string groupKey: ""
    property bool collapsed: false
    property int toolCount: 0
    property int groupIndex: 0
    property bool hovered: false
    property bool dragging: false

    implicitHeight: Math.max(38, Theme.sp(34))
    height: implicitHeight

    Rectangle {
        anchors.fill: parent
        color: row.hovered ? Theme.paperRaised : Theme.paper
        border.width: Theme.lineWidth
        border.color: Theme.line

        Behavior on color { ColorAnimation { duration: Theme.fast } }
    }
    Rectangle {
        width: 4
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: row.groupKey.length ? Theme.telemetry : Theme.faint
    }
    VectorIcon {
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        name: "collapse"
        color: row.groupKey.length ? Theme.telemetryDark : Theme.faint
        opticalY: 0.3
        width: 18
        height: 18
        rotation: row.collapsed ? 180 : 0

        Behavior on rotation { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeStandard } }
    }
    Text {
        anchors.left: parent.left
        anchors.leftMargin: 43
        anchors.right: count.left
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        text: "GROUP / " + (row.groupName || "未分组").toUpperCase()
        color: row.groupKey.length ? Theme.text : Theme.muted
        font.family: Theme.mono
        font.pixelSize: Theme.sp(9)
        font.weight: Font.Bold
        elide: Text.ElideRight
    }
    Text {
        id: count
        anchors.right: handle.left
        anchors.rightMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        text: String(row.toolCount).padStart(2, "0")
        color: Theme.faint
        font.family: Theme.mono
        font.pixelSize: Theme.sp(9)
    }
    VectorIcon {
        id: handle
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        name: "drag"
        color: Theme.faint
        width: 16
        height: 16
        opacity: row.hovered || row.dragging ? 1 : 0.62

        Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
    }
}
