import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: cell

    property string label: "FIELD"
    property string value: "--"
    property bool multiline: false

    implicitHeight: multiline ? 92 : 72

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        spacing: 7

        Text {
            Layout.fillWidth: true
            text: cell.label.toUpperCase()
            color: Theme.faint
            font.family: Theme.mono
            font.pixelSize: Theme.sp(7)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: cell.value || "--"
            color: Theme.text
            font.family: Theme.mono
            font.pixelSize: Theme.sp(10)
            wrapMode: cell.multiline ? Text.WrapAnywhere : Text.NoWrap
            elide: cell.multiline ? Text.ElideNone : Text.ElideMiddle
            verticalAlignment: Text.AlignTop
        }
    }
}
