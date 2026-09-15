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
    property real slideOffset: 0
    property var launchData: null
    property var readinessData: ({"mode": "auto", "grace_seconds": 3, "timeout_seconds": 120, "health_url": "", "health_port": null})
    property var checksData: []
    property var setupCommands: []
    property string sourcePath: ""
    property bool rawMode: false
    property bool advancedExpanded: false
    property bool setupRequired: false
    property bool setupNetwork: false
    property string setupSummary: ""
    property string setupTarget: ""
    property bool setupRunning: false
    property string setupToken: ""
    property string setupProgressText: ""
    property string setupLogPath: ""
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
        launchData = read(data, "launch", null)
        readinessData = read(data, "readiness", {"mode": "auto", "grace_seconds": 3, "timeout_seconds": 120, "health_url": "", "health_port": null})
        var readinessIndex = readinessMode.find(String(read(readinessData, "mode", "auto")))
        readinessMode.currentIndex = readinessIndex >= 0 ? readinessIndex : 0
        startupTimeoutField.text = Number(read(readinessData, "timeout_seconds", 120)).toFixed(0)
        healthUrlField.text = String(read(readinessData, "health_url", ""))
        var configuredPort = read(readinessData, "health_port", null)
        healthPortField.text = configuredPort === null ? "" : String(configuredPort)
        checksData = read(data, "checks", [])
        setupCommands = read(data, "setupCommands", [])
        sourcePath = String(read(data, "source", launchData ? launchData.source : ""))
        rawMode = Boolean(read(data, "rawMode", launchData === null && originalId.length > 0))
        advancedExpanded = rawMode && originalId.length > 0
        setupRequired = Boolean(read(data, "setupRequired", false))
        setupNetwork = Boolean(read(data, "setupNetwork", false))
        setupSummary = String(read(data, "setupSummary", ""))
        setupTarget = String(read(data, "setupTarget", ""))
        setupRunning = false
        setupToken = ""
        setupProgressText = ""
        setupLogPath = ""
        idWasSuggested = originalId.length === 0
        open()
        nameField.forceActiveFocus()
    }

    function applyLaunchPatch(patch) {
        if (!patch || !patch.launch)
            return
        if (nameField.text.trim().length === 0)
            nameField.text = String(patch.name || "")
        if (originalId.length === 0 && idWasSuggested)
            idField.text = String(patch.suggestedId || idField.text)
        sourcePath = String(patch.source || "")
        cwdField.text = String(patch.cwd || "")
        commandField.text = String(patch.cmd || "")
        shellField.text = String(patch.shell || shellField.text)
        launchData = patch.launch
        readinessData = patch.readiness || readinessData
        checksData = patch.checks || []
        setupCommands = patch.setupCommands || []
        setupRequired = Boolean(patch.setupRequired)
        setupNetwork = Boolean(patch.setupNetwork)
        setupSummary = String(patch.setupSummary || "")
        setupTarget = String(patch.setupTarget || "")
        rawMode = false
    }

    function submit() {
        readinessData = {
            "mode": readinessMode.currentText,
            "grace_seconds": Number(read(readinessData, "grace_seconds", 3)),
            "timeout_seconds": Number(startupTimeoutField.text),
            "health_url": healthUrlField.text.trim(),
            "health_port": healthPortField.text.trim().length > 0 ? Number(healthPortField.text) : null
        }
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
            "stopTimeout": Number(timeoutField.text),
            "launch": rawMode ? null : launchData,
            "readiness": readinessData,
            "rawMode": rawMode,
            "source": sourcePath,
            "checks": checksData,
            "setupRequired": setupRequired,
            "setupSummary": setupSummary,
            "setupTarget": setupTarget,
            "setupNetwork": setupNetwork,
            "setupCommands": setupCommands
        }
        var saved = mode === "edit" ? bridge.saveToolDraft(payload) : bridge.saveAndStartToolDraft(payload)
        if (saved)
            close()
    }

    parent: Overlay.overlay
    x: parent.width - width + slideOffset
    y: 0
    width: Math.min(780, parent.width - 48)
    height: parent.height
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    Overlay.modal: Rectangle { color: Theme.scrimStrong }

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
                            background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: nameField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                            onTextEdited: {
                                if (editor.originalId.length === 0 && editor.idWasSuggested)
                                    idField.text = editor.bridge.suggestToolId(text)
                            }
                        }
                    }

                    ColumnLayout {
                        visible: editor.advancedExpanded
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
                            background: Rectangle { color: idField.readOnly ? Theme.fog : Theme.paper; border.width: Theme.lineWidth; border.color: idField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
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
                        Layout.fillWidth: true
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
                            background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: groupField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                        }
                    }

                    ColumnLayout {
                        visible: editor.advancedExpanded
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
                                background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: cwdField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                            }
                            ActionButton { iconName: "folder"; tip: "选择工作目录"; onClicked: folderDialog.open() }
                        }
                    }
                }

                Text {
                    text: "02 / STARTUP SOURCE"
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
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        TextField {
                            id: sourceField
                            objectName: "editorSource"
                            Layout.fillWidth: true
                            readOnly: true
                            placeholderText: "选择程序或启动脚本"
                            text: editor.sourcePath
                            color: text.length > 0 ? Theme.text : Theme.faint
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: Theme.line; radius: Theme.radiusSmall }
                        }
                        ActionButton { iconName: "folder"; label: "选择"; tip: "选择程序或脚本"; enabled: !editor.setupRunning; onClicked: launchDialog.open() }
                    }

                    Repeater {
                        model: editor.checksData || []
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 8
                            Rectangle {
                                Layout.preferredWidth: 7
                                Layout.preferredHeight: 7
                                radius: Theme.radiusTiny
                                color: modelData.level === "blocking" ? Theme.danger : modelData.level === "warning" ? Theme.warning : Theme.telemetry
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.message || ""
                                color: modelData.level === "blocking" ? Theme.danger : Theme.muted
                                font.family: Theme.sans
                                font.pixelSize: Theme.sp(11)
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    Rectangle {
                        objectName: "editorSetupPanel"
                        visible: editor.setupRequired || editor.setupRunning || editor.setupLogPath.length > 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: setupColumn.implicitHeight + 20
                        color: Theme.fog
                        border.width: Theme.lineWidth
                        border.color: editor.setupRequired ? Theme.warning : Theme.line
                        radius: Theme.radiusSmall

                        ColumnLayout {
                            id: setupColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 7
                            Text {
                                Layout.fillWidth: true
                                text: editor.setupRunning ? editor.setupProgressText : editor.setupRequired ? editor.setupSummary : "环境准备完成"
                                color: editor.setupRequired ? Theme.text : Theme.telemetryDark
                                font.family: Theme.sans
                                font.pixelSize: Theme.sp(12)
                                font.weight: Font.DemiBold
                                wrapMode: Text.Wrap
                            }
                            Text {
                                visible: editor.setupTarget.length > 0
                                Layout.fillWidth: true
                                text: editor.setupTarget
                                color: Theme.muted
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(10)
                                elide: Text.ElideMiddle
                            }
                            RowLayout {
                                visible: editor.setupLogPath.length > 0
                                Layout.fillWidth: true
                                spacing: 8
                                Text {
                                    objectName: "editorSetupLogPath"
                                    Layout.fillWidth: true
                                    text: "日志 · " + editor.setupLogPath
                                    color: Theme.muted
                                    font.family: Theme.mono
                                    font.pixelSize: Theme.sp(9)
                                    elide: Text.ElideMiddle
                                }
                                ActionButton {
                                    objectName: "editorSetupLogAction"
                                    iconName: "folder"
                                    tip: "定位完整准备日志"
                                    onClicked: editor.bridge.openSetupLog(editor.setupLogPath)
                                }
                            }
                            Text {
                                visible: editor.setupRequired && !editor.setupRunning
                                Layout.fillWidth: true
                                text: (editor.setupCommands || []).join("\n")
                                color: Theme.muted
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(9)
                                wrapMode: Text.WrapAnywhere
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Item { Layout.fillWidth: true }
                                ActionButton {
                                    objectName: "editorSetupCancel"
                                    visible: editor.setupRunning
                                    iconName: "close"
                                    label: "取消准备"
                                    onClicked: editor.bridge.cancelEnvironmentPreparation(editor.setupToken)
                                }
                                ActionButton {
                                    objectName: "editorSetupAction"
                                    visible: editor.setupRequired && !editor.setupRunning
                                    iconName: "play"
                                    label: editor.setupNetwork ? "确认联网并准备" : "确认并准备"
                                    kind: "command"
                                    onClicked: {
                                        editor.setupToken = editor.bridge.prepareEnvironmentForPath(editor.sourcePath)
                                        editor.setupRunning = editor.setupToken.length > 0
                                        if (editor.setupRunning)
                                            editor.setupProgressText = "正在准备项目环境"
                                    }
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        ActionButton {
                            objectName: "editorAdvancedToggle"
                            iconName: "settings"
                            label: editor.advancedExpanded ? "收起高级设置" : "高级设置"
                            onClicked: editor.advancedExpanded = !editor.advancedExpanded
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.leftMargin: 28; Layout.rightMargin: 28; color: Theme.line }

                Text {
                    objectName: "editorAdvancedExecution"
                    visible: editor.advancedExpanded
                    text: "03 / EXECUTION"
                    color: Theme.command
                    font.family: Theme.mono
                    font.pixelSize: Theme.sp(10)
                    font.weight: Font.Bold
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                }

                ColumnLayout {
                    visible: editor.advancedExpanded
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "启动命令"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                        Item { Layout.fillWidth: true }
                        Switch {
                            id: rawModeSwitch
                            objectName: "editorRawMode"
                            text: "原始命令"
                            checked: editor.rawMode
                            onToggled: editor.rawMode = checked
                        }
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 112
                        TextArea {
                            id: commandField
                            objectName: "editorCommand"
                            placeholderText: "python app.py --port 8000"
                            readOnly: !editor.rawMode
                            selectByMouse: true
                            wrapMode: TextEdit.NoWrap
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: commandField.readOnly ? Theme.fog : Theme.paper; border.width: Theme.lineWidth; border.color: commandField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                        }
                    }
                }

                RowLayout {
                    visible: editor.advancedExpanded
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
                            readOnly: !editor.rawMode
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            background: Rectangle { color: shellField.readOnly ? Theme.fog : Theme.paper; border.width: Theme.lineWidth; border.color: shellField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
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
                            background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: stopSignal.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                            popup: Popup {
                                y: stopSignal.height + 2
                                width: stopSignal.width
                                implicitHeight: contentItem.implicitHeight
                                padding: 1
                                background: Rectangle { color: Theme.paperRaised; border.width: Theme.lineWidth; border.color: Theme.ink; radius: Theme.radiusSmall }
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
                            background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: timeoutField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                        }
                    }
                }

                Rectangle { visible: editor.advancedExpanded; Layout.fillWidth: true; Layout.preferredHeight: 1; Layout.leftMargin: 28; Layout.rightMargin: 28; color: Theme.line }

                Text {
                    visible: editor.advancedExpanded
                    text: "04 / ENVIRONMENT & READINESS"
                    color: Theme.command
                    font.family: Theme.mono
                    font.pixelSize: Theme.sp(10)
                    font.weight: Font.Bold
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                }

                ColumnLayout {
                    visible: editor.advancedExpanded
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
                            background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: envField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        spacing: 12
                        ColumnLayout {
                            Layout.preferredWidth: 150
                            Text { text: "就绪方式"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                            ComboBox {
                                id: readinessMode
                                Layout.fillWidth: true
                                model: ["auto", "process", "http", "tcp"]
                            }
                        }
                        ColumnLayout {
                            Layout.preferredWidth: 130
                            Text { text: "启动超时 / 秒"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                            TextField {
                                id: startupTimeoutField
                                Layout.fillWidth: true
                                validator: DoubleValidator { bottom: 0.1; top: 86400; decimals: 1 }
                                background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: startupTimeoutField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Text { text: "本地健康地址"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                            TextField {
                                id: healthUrlField
                                Layout.fillWidth: true
                                placeholderText: "http://127.0.0.1:8000/health"
                                background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: healthUrlField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                            }
                        }
                        ColumnLayout {
                            Layout.preferredWidth: 100
                            Text { text: "TCP 端口"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(11) }
                            TextField {
                                id: healthPortField
                                Layout.fillWidth: true
                                validator: IntValidator { bottom: 1; top: 65535 }
                                background: Rectangle { color: Theme.paper; border.width: Theme.lineWidth; border.color: healthPortField.activeFocus ? Theme.command : Theme.line; radius: Theme.radiusSmall }
                            }
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
                            radius: Theme.radiusSmall
                            color: autostart.checked ? Theme.telemetry : Theme.fog
                            border.width: Theme.lineWidth
                            border.color: autostart.checked ? Theme.telemetryDark : Theme.line
                            Rectangle {
                                width: 14
                                height: 14
                                y: 3
                                x: autostart.checked ? parent.width - width - 3 : 3
                                radius: Theme.radiusTiny
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
                ActionButton {
                    objectName: "editorPrimaryAction"
                    iconName: editor.mode === "edit" ? "arrow" : "play"
                    label: editor.mode === "edit" ? "保存" : "添加并启动"
                    kind: "command"
                    enabled: !editor.setupRunning && (!editor.setupRequired || editor.rawMode) && nameField.text.trim().length > 0 && (editor.rawMode ? commandField.text.trim().length > 0 : editor.launchData !== null)
                    onClicked: editor.submit()
                }
            }
        }
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.normal }
            NumberAnimation { target: editor; property: "slideOffset"; from: Theme.shiftMedium * 3; to: 0; duration: Theme.normal + Theme.fast / 2; easing.type: Theme.easeEnter }
        }
    }
    exit: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.fast; easing.type: Theme.easeExit }
            NumberAnimation { target: editor; property: "slideOffset"; to: Theme.shiftMedium * 2; duration: Theme.normal; easing.type: Theme.easeExit }
        }
    }

    Connections {
        target: editor.bridge

        function onSetupProgressChanged(event) {
            if (!event || String(event.token) !== editor.setupToken)
                return
            if (event.logPath)
                editor.setupLogPath = String(event.logPath)
            if (Number(event.current) > 0)
                editor.setupProgressText = "步骤 " + event.current + " / " + event.total + " · " + event.command
        }

        function onSetupFinished(event) {
            if (!event || (editor.setupToken.length > 0 && String(event.token) !== editor.setupToken))
                return
            editor.setupRunning = false
            editor.setupToken = ""
            editor.setupLogPath = String(event.logPath || "")
            editor.setupProgressText = String(event.message || "")
            if (event.success && event.patch)
                editor.applyLaunchPatch(event.patch)
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
        nameFilters: ["程序、脚本或本机程序 (*.exe *.bat *.cmd *.ps1 *.py *.sh *)", "所有文件 (*)"]
        onAccepted: {
            var patch = editor.bridge.launchDraftForPath(selectedFile.toString(), shellField.text)
            editor.applyLaunchPatch(patch)
        }
    }
}
