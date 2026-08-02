import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as Platform
import ".."

Popup {
    id: editor
    objectName: "toolEditor"

    required property var bridge
    property string mode: "add"
    property string originalId: ""
    property bool idWasSuggested: true
    signal deleteRequested()

    function read(data, key, fallback) {
        var value = data ? data[key] : undefined
        return value === undefined || value === null ? fallback : value
    }

    function openWith(nextMode, data) {
        mode = nextMode
        originalId = String(read(data, "originalId", ""))
        idField.text = String(read(data, "id", "tool"))
        nameField.text = String(read(data, "name", ""))
        groupField.text = String(read(data, "group", ""))
        cwdField.text = String(read(data, "cwd", ""))
        commandField.text = String(read(data, "cmd", ""))
        shellField.text = String(read(data, "shell", "/bin/bash"))
        envField.text = String(read(data, "envText", ""))
        autostart.checked = Boolean(read(data, "autostart", false))
        var signalValue = String(read(data, "stopSignal", "TERM"))
        var signalIndex = stopSignal.find(signalValue)
        stopSignal.currentIndex = signalIndex >= 0 ? signalIndex : 0
        timeoutField.text = Number(read(data, "stopTimeout", 10)).toFixed(1)
        idWasSuggested = originalId.length === 0
        open()
        nameField.forceActiveFocus()
    }

    function submit() {
        var payload = {
            "originalId": originalId,
            "id": idField.text.trim(),
            "name": nameField.text.trim(),
            "group": groupField.text.trim(),
            "cwd": cwdField.text.trim(),
            "cmd": commandField.text,
            "shell": shellField.text.trim(),
            "envText": envField.text,
            "autostart": autostart.checked,
            "stopSignal": stopSignal.currentText,
            "stopTimeout": Number(timeoutField.text)
        }
        if (bridge.saveToolDraft(payload))
            close()
    }

    parent: Overlay.overlay
    x: parent.width - width
    y: 0
    width: Math.min(780, parent.width - 48)
    height: parent.height
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    Overlay.modal: Rectangle { color: "#a60d100e" }

    background: Rectangle {
        color: Theme.paperRaised
        border.width: 0

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 7
            color: Theme.command
        }
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(92, Theme.sp(72))
            color: Theme.ink

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 28
                anchors.rightMargin: 20
                spacing: 12

                ColumnLayout {
                    spacing: 3
                    Layout.fillWidth: true

                    Text {
                        text: editor.mode === "edit" ? "UNIT CONFIGURATION / REVISION" : "UNIT CONFIGURATION / REGISTER"
                        color: Theme.telemetry
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(9)
                        font.weight: Font.Bold
                    }

                    Text {
                        text: editor.mode === "edit" ? "编辑工具" : editor.mode === "import" ? "登记导入工具" : "添加工具"
                        color: Theme.white
                        font.family: Theme.condensed
                        font.pixelSize: Theme.sp(27)
                        font.weight: Font.Bold
                    }
                }
            }
        }

        ScrollView {
            id: formScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: formScroll.availableWidth
                spacing: 18

                Item { Layout.preferredHeight: 4 }

                Text {
                    text: "01 / IDENTITY"
                    color: Theme.command
                    font.family: Theme.mono
                    font.pixelSize: Theme.sp(10)
                    font.weight: Font.Bold
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    spacing: 16

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Text { text: "工具名称"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        TextField {
                            id: nameField
                            objectName: "editorName"
                            Layout.fillWidth: true
                            placeholderText: "例如：ComfyUI"
                            selectByMouse: true
                            color: Theme.text
                            font.family: Theme.sans
                            font.pixelSize: Theme.sp(14)
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: nameField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                            onTextEdited: {
                                if (editor.originalId.length === 0 && editor.idWasSuggested)
                                    idField.text = editor.bridge.suggestToolId(text)
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Text { text: "工具 ID"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        TextField {
                            id: idField
                            objectName: "editorId"
                            Layout.fillWidth: true
                            readOnly: editor.originalId.length > 0
                            selectByMouse: true
                            color: readOnly ? Theme.faint : Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(13)
                            background: Rectangle { color: idField.readOnly ? Theme.fog : Theme.paper; border.width: 1; border.color: idField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                            onTextEdited: editor.idWasSuggested = false
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    spacing: 16

                    ColumnLayout {
                        Layout.preferredWidth: 210
                        spacing: 6
                        Text { text: "自定义分组"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        TextField {
                            id: groupField
                            objectName: "editorGroup"
                            Layout.fillWidth: true
                            placeholderText: "未分组"
                            selectByMouse: true
                            maximumLength: 64
                            color: Theme.text
                            font.family: Theme.sans
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: groupField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Text { text: "工作目录"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TextField {
                                id: cwdField
                                objectName: "editorCwd"
                                Layout.fillWidth: true
                                selectByMouse: true
                                color: Theme.text
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(12)
                                background: Rectangle { color: Theme.paper; border.width: 1; border.color: cwdField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                            }
                            ActionButton { iconName: "folder"; tip: "选择工作目录"; onClicked: folderDialog.open() }
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.leftMargin: 28; Layout.rightMargin: 28; color: Theme.line }

                Text {
                    text: "02 / EXECUTION"
                    color: Theme.command
                    font.family: Theme.mono
                    font.pixelSize: Theme.sp(10)
                    font.weight: Font.Bold
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "启动命令"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        Item { Layout.fillWidth: true }
                        ActionButton { iconName: "folder"; label: "选择程序"; tip: "选择程序或脚本"; onClicked: launchDialog.open() }
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 112
                        TextArea {
                            id: commandField
                            objectName: "editorCommand"
                            placeholderText: "python app.py --port 8000"
                            selectByMouse: true
                            wrapMode: TextEdit.NoWrap
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: commandField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    spacing: 16

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Text { text: "命令解释器"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        TextField {
                            id: shellField
                            Layout.fillWidth: true
                            selectByMouse: true
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: shellField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                        }
                    }

                    ColumnLayout {
                        Layout.preferredWidth: 160
                        spacing: 6
                        Text { text: "停止信号"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        ComboBox {
                            id: stopSignal
                            Layout.fillWidth: true
                            model: ["TERM", "INT", "HUP", "QUIT", "KILL"]
                            font.family: Theme.mono
                            leftPadding: 11
                            rightPadding: 30
                            contentItem: Text {
                                text: stopSignal.displayText
                                color: Theme.text
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(12)
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                            indicator: Text {
                                x: stopSignal.width - width - 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: "⌄"
                                color: Theme.muted
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(14)
                            }
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: stopSignal.activeFocus ? Theme.command : Theme.line; radius: 2 }
                            popup: Popup {
                                y: stopSignal.height + 2
                                width: stopSignal.width
                                implicitHeight: contentItem.implicitHeight
                                padding: 1
                                background: Rectangle { color: Theme.paperRaised; border.width: 1; border.color: Theme.ink; radius: 2 }
                                contentItem: ListView {
                                    clip: true
                                    implicitHeight: contentHeight
                                    model: stopSignal.popup.visible ? stopSignal.delegateModel : null
                                    currentIndex: stopSignal.highlightedIndex
                                    ScrollIndicator.vertical: ScrollIndicator { }
                                }
                            }
                            delegate: ItemDelegate {
                                required property int index
                                required property var modelData
                                width: stopSignal.width - 2
                                height: 32
                                highlighted: stopSignal.highlightedIndex === index
                                contentItem: Text {
                                    text: modelData
                                    color: highlighted ? Theme.white : Theme.text
                                    font.family: Theme.mono
                                    font.pixelSize: Theme.sp(11)
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle { color: highlighted ? Theme.ink : parent.hovered ? Theme.fog : "transparent" }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.preferredWidth: 130
                        spacing: 6
                        Text { text: "停止等待 / 秒"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        TextField {
                            id: timeoutField
                            Layout.fillWidth: true
                            validator: DoubleValidator { bottom: 0; top: 3600; decimals: 1 }
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: timeoutField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.leftMargin: 28; Layout.rightMargin: 28; color: Theme.line }

                Text {
                    text: "03 / ENVIRONMENT"
                    color: Theme.command
                    font.family: Theme.mono
                    font.pixelSize: Theme.sp(10)
                    font.weight: Font.Bold
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    spacing: 6
                    Text { text: "环境变量 / 每行 KEY=VALUE"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 94
                        TextArea {
                            id: envField
                            objectName: "editorEnvironment"
                            placeholderText: "PORT=8000"
                            selectByMouse: true
                            wrapMode: TextEdit.NoWrap
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: Theme.paper; border.width: 1; border.color: envField.activeFocus ? Theme.command : Theme.line; radius: 2 }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    Layout.bottomMargin: 24
                    spacing: 10

                    Switch {
                        id: autostart
                        text: "启动 Lattice 时自动运行"
                        spacing: 9
                        indicator: Rectangle {
                            implicitWidth: 38
                            implicitHeight: 20
                            x: 0
                            anchors.verticalCenter: parent.verticalCenter
                            radius: 2
                            color: autostart.checked ? Theme.telemetry : Theme.fog
                            border.width: 1
                            border.color: autostart.checked ? Theme.telemetryDark : Theme.line
                            Rectangle {
                                width: 14
                                height: 14
                                y: 3
                                x: autostart.checked ? parent.width - width - 3 : 3
                                radius: 1
                                color: autostart.checked ? Theme.ink : Theme.faint
                                Behavior on x { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
                            }
                        }
                        contentItem: Text {
                            text: autostart.text
                            color: Theme.text
                            font.family: Theme.sans
                            font.pixelSize: Theme.sp(12)
                            leftPadding: autostart.indicator.width + autostart.spacing
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Item { Layout.fillWidth: true }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 72
            color: Theme.paper
            border.width: 0

            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 28
                anchors.rightMargin: 20
                spacing: 8

                ActionButton {
                    visible: editor.mode === "edit"
                    iconName: "close"
                    label: "删除"
                    kind: "danger"
                    onClicked: {
                        editor.close()
                        editor.deleteRequested()
                    }
                }
                Item { Layout.fillWidth: true }
                ActionButton { label: "取消"; onClicked: editor.close() }
                ActionButton { iconName: "arrow"; label: "写入配置"; kind: "command"; onClicked: editor.submit() }
            }
        }
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.normal }
            NumberAnimation { property: "x"; from: editor.parent ? editor.parent.width : 0; to: editor.parent ? editor.parent.width - editor.width : 0; duration: Theme.slow; easing.type: Easing.OutCubic }
        }
    }
    exit: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.normal }
            NumberAnimation { property: "x"; to: editor.parent ? editor.parent.width : 0; duration: Theme.normal; easing.type: Easing.InCubic }
        }
    }

    Platform.FolderDialog {
        id: folderDialog
        title: "选择工作目录"
        onAccepted: cwdField.text = editor.bridge.pathFromUrl(selectedFolder.toString())
    }

    Platform.FileDialog {
        id: launchDialog
        title: "选择程序或脚本"
        nameFilters: ["程序或脚本 (*.exe *.bat *.cmd *.ps1 *.py *.sh)", "所有文件 (*)"]
        onAccepted: {
            var patch = editor.bridge.launchDraftForPath(selectedFile.toString(), shellField.text)
            if (!patch || !patch.cmd)
                return
            if (nameField.text.trim().length === 0)
                nameField.text = patch.name
            if (editor.originalId.length === 0 && editor.idWasSuggested)
                idField.text = patch.suggestedId
            cwdField.text = patch.cwd
            commandField.text = patch.cmd
            shellField.text = patch.shell
        }
    }
}
