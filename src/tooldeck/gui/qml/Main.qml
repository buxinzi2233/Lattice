import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as Platform
import "."
import "components"

ApplicationWindow {
    id: root
    objectName: "mainWindow"
    visible: true
    width: 1280
    height: 800
    minimumWidth: 1024
    minimumHeight: 700
    title: "Lattice / Local Operations"
    color: Theme.paper

    property var selectedData: AppBridge.selected
    property string pendingImportPath: ""
    property int dropTargetRow: -1
    property real dropTargetY: -1
    property string draggingLabel: ""
    property real operationsSelectionReveal: 1
    readonly property bool hasSelection: AppBridge.selectedId.length > 0

    function updateDropTarget(y) {
        if (!AppBridge.reorderingAllowed)
            return
        var row = toolList.indexAt(8, y)
        if (row < 0)
            row = AppBridge.toolModel.rowCount() - 1
        dropTargetRow = row
        var target = toolList.itemAtIndex(row)
        dropTargetY = target ? target.y + (y > target.y + target.height / 2 ? target.height : 0) : y
    }

    function commitDrop(sourceKind, sourceGroup, sourceTool, y) {
        if (!AppBridge.reorderingAllowed)
            return
        updateDropTarget(y)
        var targetRow = AppBridge.toolModel.getRow(dropTargetRow)
        if (!targetRow || !targetRow.rowType)
            return
        if (sourceKind === "group") {
            var groupIndex = Number(targetRow.groupIndex)
            if (targetRow.rowType === "group" && y > dropTargetY)
                groupIndex += 1
            AppBridge.moveGroup(sourceGroup, groupIndex)
            return
        }
        var targetGroup = targetRow.rowType === "group" ? targetRow.groupKey : targetRow.groupKey
        var targetIndex = targetRow.rowType === "group" ? Number(targetRow.groupToolCount) : Number(targetRow.toolIndex)
        if (targetRow.rowType === "tool" && y > dropTargetY)
            targetIndex += 1
        AppBridge.moveTool(sourceTool, targetGroup, targetIndex)
    }

    function syncTheme() {
        Theme.applyTokens(AppBridge.themeTokens)
    }

    function revealOperationsSelection() {
        if (!operationsShell.visible) {
            operationsSelectionReveal = 1
            return
        }
        operationsSelectionAnimation.restart()
    }

    Binding {
        target: Theme
        property: "fontScale"
        value: AppBridge.fontScale
    }

    NumberAnimation {
        id: operationsSelectionAnimation
        objectName: "operationsSelectionAnimation"
        target: root
        property: "operationsSelectionReveal"
        from: 0
        to: 1
        duration: Theme.normal
        easing.type: Theme.easeEnter
    }

    Component.onCompleted: {
        syncTheme()
        if (AppBridge.startupAutoLaunch && AppBridge.startupShouldShow)
            startupExperience.show(false)
    }

    function value(key, fallback) {
        var current = selectedData ? selectedData[key] : undefined
        return current === undefined || current === null ? fallback : current
    }

    onClosing: function(close) {
        if (!AppBridge.acceptWindowClose()) {
            close.accepted = false
            root.hide()
        }
    }

    RowLayout {
        id: operationsShell
        objectName: "operationsShell"
        anchors.fill: parent
        spacing: 0
        visible: AppBridge.themeShell !== "archive"
        enabled: visible

        Rectangle {
            id: rail
            objectName: "commandRail"
            Layout.preferredWidth: 68
            Layout.fillHeight: true
            color: Theme.ink

            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 14
                anchors.bottomMargin: 14
                spacing: 10

                Item {
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 52
                    Layout.alignment: Qt.AlignHCenter

                    Image {
                        objectName: "brandMark"
                        width: 34
                        height: 34
                        anchors.horizontalCenter: parent.horizontalCenter
                        source: "../assets/lattice-mark.svg"
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        text: "OPS"
                        color: Theme.faintOnDark
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(8)
                        font.weight: Font.Bold
                    }
                }

                Rectangle { Layout.preferredWidth: 32; Layout.preferredHeight: 1; Layout.alignment: Qt.AlignHCenter; color: Theme.lineDark }

                RailButton {
                    iconName: "plus"
                    symbolSize: 22
                    symbolYOffset: -1
                    tip: "添加工具"
                    active: toolEditor.opened && toolEditor.mode === "add"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: toolEditor.openWith("add", AppBridge.newToolDraft())
                }
                RailButton {
                    iconName: "download"
                    symbolSize: 21
                    symbolYOffset: -1
                    tip: "导入工具或配置"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: importDialog.open()
                }
                RailButton {
                    iconName: "refresh"
                    symbolSize: 20
                    tip: "重载配置"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: AppBridge.reloadTools(true)
                }
                RailButton {
                    iconName: "home"
                    symbolSize: 20
                    symbolYOffset: -1
                    tip: "打开配置目录"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: AppBridge.openConfigDirectory()
                }

                Item { Layout.fillHeight: true }

                RailButton {
                    objectName: "interfaceSettingsAction"
                    iconName: "settings"
                    tip: "界面与启动设置"
                    active: settingsPanel.opened
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: settingsPanel.opened ? settingsPanel.close() : settingsPanel.open()
                }
                RailButton {
                    iconName: "stop"
                    symbolSize: 16
                    tip: "停止全部活动工具"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: {
                        if (AppBridge.toolModel.runningCount > 0)
                            confirmPanel.ask("stop-all", "停止全部活动单元", "将向当前所有活动进程组发送停止指令。", "停止全部", "danger")
                        else
                            toast.show("当前没有活动单元", "warning")
                    }
                }
                RailButton {
                    iconName: "close"
                    symbolSize: 22
                    symbolYOffset: -1
                    tip: "退出 Lattice"
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: confirmPanel.ask("exit", "退出晶格中枢", "活动工具不会自动停止；仅退出 Lattice 控制界面。", "退出", "danger")
                }
            }
        }

        Rectangle {
            id: processIndex
            objectName: "processIndex"
            Layout.preferredWidth: Math.max(264, Math.min(320, root.width * 0.245))
            Layout.fillHeight: true
            color: Theme.fog

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 80

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 18
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3

                        Text {
                            text: "PROCESS INDEX"
                            color: Theme.command
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(9)
                            font.weight: Font.Bold
                        }
                        Text {
                            text: "工具序列"
                            color: Theme.text
                            font.family: Theme.condensed
                            font.pixelSize: Theme.sp(24)
                            font.weight: Font.Bold
                        }
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 18
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 17
                        text: String(AppBridge.toolModel.totalCount).padStart(2, "0")
                        color: Theme.faint
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(22)
                        font.weight: Font.Bold
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }

                TextField {
                    id: searchField
                    objectName: "toolSearch"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    Layout.topMargin: 10
                    placeholderText: "名称 / ID / 路径 / 分组"
                    text: AppBridge.searchText
                    leftPadding: 12
                    rightPadding: 12
                    selectByMouse: true
                    color: Theme.text
                    font.family: Theme.sans
                    font.pixelSize: Theme.sp(12)
                    onTextEdited: AppBridge.setSearchText(text)
                    background: Rectangle {
                        color: Theme.paperRaised
                        border.width: Theme.lineWidth
                        border.color: searchField.activeFocus ? Theme.command : Theme.line
                        radius: Theme.radiusSmall
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    spacing: 2

                    Repeater {
                        model: [
                            { key: "all", label: "全部" },
                            { key: "running", label: "运行 " + AppBridge.toolModel.runningCount },
                            { key: "stopped", label: "静止 " + AppBridge.toolModel.idleCount },
                            { key: "exited", label: "异常 " + AppBridge.toolModel.exitedCount }
                        ]

                        Button {
                            id: filterButton
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 30
                            text: modelData.label
                            hoverEnabled: true
                            onClicked: AppBridge.setFilterMode(modelData.key)
                            transform: Translate {
                                y: filterButton.down ? 1 : 0
                                Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                            }
                            contentItem: Text {
                                text: filterButton.text
                                color: AppBridge.filterMode === filterButton.modelData.key ? Theme.white : Theme.muted
                                font.family: Theme.sans
                                font.pixelSize: Theme.sp(10)
                                font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                color: AppBridge.filterMode === filterButton.modelData.key ? Theme.ink : filterButton.hovered ? Theme.paperRaised : "transparent"
                                border.width: Theme.lineWidth
                                border.color: AppBridge.filterMode === filterButton.modelData.key ? Theme.ink : Theme.line
                                radius: Theme.radiusSmall
                                Behavior on color { ColorAnimation { duration: Theme.fast } }
                                Behavior on border.color { ColorAnimation { duration: Theme.fast } }
                            }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ListView {
                        id: toolList
                        objectName: "toolList"
                        anchors.fill: parent
                        model: AppBridge.toolModel
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        currentIndex: -1
                        delegate: Item {
                            id: rowDelegate
                            property string rowKind: rowType
                            property string rowGroupName: groupName
                            property string rowGroupKey: groupKey
                            property bool rowCollapsed: Boolean(collapsed)
                            property int rowGroupIndex: groupIndex
                            property int rowToolIndex: toolIndex
                            property int rowGroupToolCount: groupToolCount
                            property bool dragging: false
                            property bool moved: false
                            property real pressX: 0
                            property real pressY: 0
                            width: ListView.view ? ListView.view.width : toolList.width
                            height: rowKind === "group" ? Math.max(38, Theme.sp(34)) : 86 + Math.max(0, Theme.sp(16) - 16) * 2
                            z: dragging ? 20 : rowKind === "group" ? 3 : 1

                            GroupRow {
                                id: groupVisual
                                visible: rowDelegate.rowKind === "group"
                                anchors.fill: parent
                                groupName: rowDelegate.rowGroupName || "未分组"
                                groupKey: rowDelegate.rowGroupKey
                                collapsed: rowDelegate.rowCollapsed
                                toolCount: rowDelegate.rowGroupToolCount
                                groupIndex: rowDelegate.rowGroupIndex
                                hovered: rowMouse.containsMouse
                                dragging: rowDelegate.dragging
                            }
                            ToolRow {
                                id: toolVisual
                                visible: rowDelegate.rowKind === "tool"
                                anchors.fill: parent
                                selected: toolId === AppBridge.selectedId
                                toolId: model.toolId || ""
                                toolName: model.toolName || ""
                                toolCwd: model.toolCwd || ""
                                toolState: model.toolState || "stopped"
                                stateLabel: model.stateLabel || ""
                                stateColor: Theme.stateColor(model.toolState || "stopped")
                                pidText: model.pidText || "----"
                                uptimeText: model.uptimeText || "--"
                                sequenceText: model.sequenceText || "--"
                                groupKey: rowDelegate.rowGroupKey
                                toolIndex: rowDelegate.rowToolIndex
                                groupToolCount: rowDelegate.rowGroupToolCount
                            }

                            MouseArea {
                                id: rowMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                preventStealing: true
                                onPressed: {
                                    rowDelegate.moved = false
                                    rowDelegate.dragging = false
                                    rowDelegate.pressX = mouse.x
                                    rowDelegate.pressY = mouse.y
                                }
                                onPositionChanged: {
                                    if (!pressed || !AppBridge.reorderingAllowed)
                                        return
                                    if (!rowDelegate.dragging && Math.hypot(mouse.x - rowDelegate.pressX, mouse.y - rowDelegate.pressY) > 6) {
                                        rowDelegate.dragging = true
                                        rowDelegate.moved = true
                                        root.draggingLabel = rowDelegate.rowKind === "group" ? rowDelegate.rowGroupName : toolVisual.toolName
                                    }
                                    if (!rowDelegate.dragging)
                                        return
                                    var p = mapToItem(toolList, mouse.x, mouse.y)
                                    if (p.y < 44)
                                        toolList.contentY = Math.max(0, toolList.contentY - 10)
                                    else if (p.y > toolList.height - 44)
                                        toolList.contentY = Math.min(toolList.contentHeight - toolList.height, toolList.contentY + 10)
                                    root.updateDropTarget(p.y)
                                }
                                onReleased: {
                                    if (!rowDelegate.dragging) {
                                        if (rowDelegate.rowKind === "group")
                                            AppBridge.toggleGroup(rowDelegate.rowGroupKey)
                                        else
                                            AppBridge.selectTool(toolVisual.toolId)
                                        return
                                    }
                                    var p = mapToItem(toolList, mouse.x, mouse.y)
                                    root.commitDrop(rowDelegate.rowKind, rowDelegate.rowGroupKey, toolVisual.toolId, p.y)
                                    rowDelegate.dragging = false
                                    root.dropTargetRow = -1
                                    root.draggingLabel = ""
                                }
                                onCanceled: {
                                    rowDelegate.dragging = false
                                    root.dropTargetRow = -1
                                    root.draggingLabel = ""
                                }
                            }
                        }

                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        Rectangle {
                            visible: root.dropTargetRow >= 0 && root.draggingLabel.length > 0
                            x: 8
                            y: root.dropTargetY - 1
                            width: toolList.width - 16
                            height: 2
                            color: Theme.command
                            z: 50
                        }
                    }

                    Column {
                        visible: AppBridge.toolModel.visibleCount === 0
                        anchors.centerIn: parent
                        width: parent.width - 48
                        spacing: 9

                        Text {
                            width: parent.width
                            text: AppBridge.toolModel.totalCount === 0 ? "NO REGISTERED UNITS" : "NO MATCHING UNITS"
                            color: Theme.text
                            font.family: Theme.mono
                            font.pixelSize: Theme.sp(12)
                            font.weight: Font.Bold
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: parent.width
                            text: AppBridge.toolModel.totalCount === 0 ? "配置索引为空" : "当前筛选无结果"
                            color: Theme.faint
                            font.family: Theme.sans
                            font.pixelSize: Theme.sp(11)
                            horizontalAlignment: Text.AlignHCenter
                        }
                        ActionButton {
                            anchors.horizontalCenter: parent.horizontalCenter
                            iconName: AppBridge.toolModel.totalCount === 0 ? "plus" : "close"
                            label: AppBridge.toolModel.totalCount === 0 ? "登记工具" : "清除筛选"
                            kind: AppBridge.toolModel.totalCount === 0 ? "command" : "neutral"
                            onClicked: {
                                if (AppBridge.toolModel.totalCount === 0)
                                    toolEditor.openWith("add", AppBridge.newToolDraft())
                                else
                                    AppBridge.clearFilters()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    color: Theme.paper

                    Rectangle { width: parent.width; height: 1; color: Theme.line }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        text: AppBridge.globalSummary
                        color: Theme.muted
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(9)
                        font.weight: Font.DemiBold
                    }
                }
            }
        }

        Rectangle {
            id: operations
            objectName: "operationsWorkspace"
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.paperRaised
            clip: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    id: telemetryBand
                    objectName: "telemetryBand"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(82, 64 + Theme.sp(18))
                    color: Theme.paper

                    RowLayout {
                        anchors.fill: parent
                        spacing: 0

                        Item {
                            Layout.preferredWidth: 174
                            Layout.fillHeight: true

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 5
                                Text { text: "SYSTEM LINK"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                                Row {
                                    spacing: 9
                                    Rectangle {
                                        width: 8
                                        height: 8
                                        radius: 4
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: AppBridge.telemetry.state === "OFFLINE" ? Theme.danger : AppBridge.telemetry.state === "PAUSED" ? Theme.warning : Theme.telemetry

                                    }
                                    Text { text: AppBridge.telemetry.stateLabel; color: Theme.text; font.family: Theme.sans; font.pixelSize: Theme.sp(12); font.weight: Font.DemiBold }
                                }
                            }
                        }

                        MetricCell { Layout.fillWidth: true; label: "CPU"; valueText: AppBridge.telemetry.cpuText; detailText: AppBridge.telemetry.cpuDetail; percent: AppBridge.telemetry.cpuValue }
                        MetricCell { Layout.fillWidth: true; label: "MEMORY"; valueText: AppBridge.telemetry.memoryText; detailText: AppBridge.telemetry.memoryDetail; percent: AppBridge.telemetry.memoryValue }
                        MetricCell { Layout.fillWidth: true; label: "GPU"; valueText: AppBridge.telemetry.gpuText; detailText: AppBridge.telemetry.gpuDetail; percent: AppBridge.telemetry.gpuValue }

                        Item {
                            Layout.preferredWidth: 112
                            Layout.fillHeight: true

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.top: parent.top
                                anchors.topMargin: 15
                                text: AppBridge.telemetry.updated
                                color: Theme.faint
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(9)
                            }
                            ActionButton {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 10
                                iconName: AppBridge.hardwarePaused ? "play" : "pause"
                                tip: AppBridge.hardwarePaused ? "恢复系统遥测" : "暂停系统遥测"
                                onClicked: AppBridge.setHardwarePaused(!AppBridge.hardwarePaused)
                            }
                        }
                    }

                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                }

                Item {
                    id: selectionHeader
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(164, 130 + Theme.sp(34))
                    opacity: 0.76 + root.operationsSelectionReveal * 0.24
                    transform: Translate { x: (1 - root.operationsSelectionReveal) * Theme.shiftSmall }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 24
                        anchors.rightMargin: 20
                        spacing: 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            RowLayout {
                                spacing: 9
                                Text {
                                    text: root.hasSelection ? "UNIT / " + root.value("id", "").toUpperCase() : "LATTICE / LOCAL OPERATIONS"
                                    color: Theme.command
                                    font.family: Theme.mono
                                    font.pixelSize: Theme.sp(10)
                                    font.weight: Font.Bold
                                }
                                Rectangle { visible: root.hasSelection; width: 24; height: 1; color: Theme.command }
                                Text {
                                    visible: root.hasSelection
                                    text: root.value("stateLabel", "")
                                    color: Theme.stateColor(root.value("state", "stopped"))
                                    font.family: Theme.sans
                                    font.pixelSize: Theme.sp(10)
                                    font.weight: Font.DemiBold
                                }
                            }

                            Text {
                                text: root.hasSelection ? root.value("name", "") : "本地运行控制中枢"
                                color: Theme.text
                                font.family: Theme.condensed
                                font.pixelSize: Theme.sp(34)
                                font.weight: Font.Black
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            Text {
                                text: root.hasSelection ? root.value("cwdShort", "") : AppBridge.globalSummary
                                color: Theme.muted
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(10)
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }

                            RowLayout {
                                visible: root.hasSelection
                                spacing: 18
                                Text { text: "PID  " + root.value("pidText", "----"); color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(9) }
                                Text { text: "UPTIME  " + root.value("uptime", "—"); color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(9) }
                                Text { text: "EXIT  " + root.value("exitCode", "--"); color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(9) }
                            }
                        }

                        RowLayout {
                            visible: root.hasSelection
                            spacing: 8
                            ActionButton { visible: root.value("readyUrl", "").length > 0; iconName: "external"; tip: "打开本地服务"; onClicked: AppBridge.openSelectedService() }
                            ActionButton { iconName: "refresh"; tip: "重启"; onClicked: AppBridge.restartSelected() }
                            ActionButton {
                                iconName: root.value("active", false) ? "stop" : "play"
                                label: root.value("active", false) ? "停止" : "启动"
                                kind: "command"
                                onClicked: root.value("active", false) ? AppBridge.stopSelected() : AppBridge.startSelected()
                            }
                        }
                    }

                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

                    Item {
                        id: selectionMotion
                        anchors.fill: parent
                        visible: false
                    }

                }

                Item {
                    id: operationsContent
                    objectName: "operationsContent"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    opacity: 0.72 + root.operationsSelectionReveal * 0.28
                    transform: Translate {
                        id: operationsContentShift
                        x: (1 - root.operationsSelectionReveal) * Theme.shiftMedium
                    }

                    RowLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            id: logConsole
                            objectName: "logConsole"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: Theme.ink

                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 43
                                    color: Theme.inkRaised

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 16
                                        anchors.rightMargin: 10
                                        spacing: 10
                                        Rectangle { width: 6; height: 6; radius: 3; color: root.value("active", false) ? Theme.telemetry : Theme.faintOnDark }
                                        Text { text: "LIVE OUTPUT"; color: Theme.white; font.family: Theme.mono; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                                        Text { text: root.hasSelection ? root.value("logPath", "") : "NO CHANNEL"; color: Theme.faintOnDark; font.family: Theme.mono; font.pixelSize: Theme.sp(9); elide: Text.ElideMiddle; Layout.fillWidth: true }
                                        CheckBox {
                                            id: followLog
                                            checked: true
                                            text: "跟随"
                                            leftPadding: 0
                                            spacing: 6
                                            indicator: Rectangle {
                                                implicitWidth: 15
                                                implicitHeight: 15
                                                x: 0
                                                anchors.verticalCenter: parent.verticalCenter
                                                radius: Theme.radiusTiny
                                                color: followLog.checked ? Theme.telemetry : "transparent"
                                                border.width: Theme.lineWidth
                                                border.color: followLog.checked ? Theme.telemetry : Theme.lineDark

                                                Behavior on color { ColorAnimation { duration: Theme.fast } }
                                                Behavior on border.color { ColorAnimation { duration: Theme.fast } }

                                                VectorIcon {
                                                    anchors.centerIn: parent
                                                    name: "check"
                                                    color: Theme.ink
                                                    width: 10
                                                    height: 10
                                                    strokeWidth: 2.2
                                                    opacity: followLog.checked ? 1 : 0
                                                    scale: followLog.checked ? 1 : 0.55

                                                    Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                                                    Behavior on scale { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeEnter } }
                                                }
                                            }
                                            contentItem: Text {
                                                text: followLog.text
                                                color: Theme.mutedOnDark
                                                font.family: Theme.sans
                                                font.pixelSize: Theme.sp(10)
                                                leftPadding: followLog.indicator.width + followLog.spacing
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                        }
                                        ActionButton { iconName: "external"; kind: "dark"; tip: "在文件管理器中定位完整日志"; enabled: root.hasSelection; onClicked: AppBridge.openSelectedLog() }
                                        ActionButton { objectName: "copyLogAction"; iconName: "copy"; kind: "dark"; tip: "复制当前显示的运行记录"; enabled: AppBridge.logText.trim().length > 0; onClicked: AppBridge.copyVisibleLog() }
                                        ActionButton { iconName: "clear"; kind: "dark"; tip: "清除当前显示"; enabled: root.hasSelection; onClicked: AppBridge.clearVisibleLog() }
                                    }
                                }

                                ScrollView {
                                    id: logScroll
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                                    TextArea {
                                        id: logText
                                        objectName: "logText"
                                        text: operations.visible ? AppBridge.logText : ""
                                        readOnly: true
                                        selectByMouse: true
                                        wrapMode: TextEdit.NoWrap
                                        color: Theme.consoleText
                                        selectionColor: Theme.command
                                        selectedTextColor: Theme.white
                                        font.family: Theme.mono
                                        font.pixelSize: Theme.sp(11)
                                        leftPadding: 16
                                        rightPadding: 16
                                        topPadding: 14
                                        bottomPadding: 14
                                        background: null
                                        onTextChanged: {
                                            if (operations.visible && followLog.checked)
                                                cursorPosition = length
                                        }
                                    }
                                }
                            }

                            Text {
                                visible: root.hasSelection && AppBridge.logText.length === 0
                                anchors.centerIn: parent
                                text: "AWAITING OUTPUT"
                                color: Theme.faintOnDark
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(13)
                                font.weight: Font.Bold
                            }
                        }

                        Rectangle {
                            id: manifest
                            objectName: "manifestPanel"
                            Layout.preferredWidth: Math.max(230, Math.min(310, operations.width * 0.31))
                            Layout.fillHeight: true
                            color: Theme.paper

                            Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: Theme.line }

                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0

                                Item {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 44
                                    Text { anchors.left: parent.left; anchors.leftMargin: 17; anchors.verticalCenter: parent.verticalCenter; text: "CONFIG MANIFEST"; color: Theme.text; font.family: Theme.mono; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                                    ActionButton { anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter; iconName: "edit"; tip: "编辑工具"; enabled: root.hasSelection; onClicked: toolEditor.openWith("edit", AppBridge.selectedToolDraft()) }
                                }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }

                                ScrollView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                                    ColumnLayout {
                                        width: manifest.width
                                        spacing: 0

                                        Repeater {
                                            model: [
                                                { label: "GROUP", value: root.value("groupLabel", "未分组") },
                                                { label: "SHELL", value: root.value("shell", "--") },
                                                { label: "STOP SIGNAL", value: root.value("stopSignal", "--") },
                                                { label: "STOP TIMEOUT", value: root.value("stopTimeout", "--") + " s" },
                                                { label: "AUTOSTART", value: root.value("autostart", false) ? "ENABLED" : "DISABLED" },
                                                { label: "ENVIRONMENT", value: root.value("envCount", 0) + " VARIABLES" }
                                            ]

                                            Item {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 58
                                                Text { anchors.left: parent.left; anchors.leftMargin: 17; anchors.top: parent.top; anchors.topMargin: 10; text: modelData.label; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(8); font.weight: Font.Bold }
                                                Text { anchors.left: parent.left; anchors.leftMargin: 17; anchors.right: parent.right; anchors.rightMargin: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 10; text: modelData.value; color: Theme.text; font.family: Theme.mono; font.pixelSize: Theme.sp(10); elide: Text.ElideMiddle }
                                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                                            }
                                        }

                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 122
                                            Text { anchors.left: parent.left; anchors.leftMargin: 17; anchors.top: parent.top; anchors.topMargin: 12; text: "COMMAND PAYLOAD"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(8); font.weight: Font.Bold }
                                            Text {
                                                anchors.left: parent.left
                                                anchors.leftMargin: 17
                                                anchors.right: parent.right
                                                anchors.rightMargin: 14
                                                anchors.top: parent.top
                                                anchors.topMargin: 34
                                                anchors.bottom: parent.bottom
                                                anchors.bottomMargin: 12
                                                text: root.value("cmd", "--")
                                                color: Theme.text
                                                font.family: Theme.mono
                                                font.pixelSize: Theme.sp(10)
                                                wrapMode: Text.WrapAnywhere
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Column {
                        visible: !root.hasSelection
                        anchors.centerIn: parent
                        spacing: 10
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "NO ACTIVE RECORD"; color: Theme.text; font.family: Theme.mono; font.pixelSize: Theme.sp(16); font.weight: Font.Bold }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "等待工具索引选择"; color: Theme.faint; font.family: Theme.sans; font.pixelSize: Theme.sp(12) }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28

                    RowLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: Theme.ink

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: "LATTICE / READY"
                                color: Theme.telemetry
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(8)
                                font.weight: Font.Bold
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: manifest.width
                            Layout.fillHeight: true
                            color: Theme.paper

                            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }
                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: "LOCAL PROCESS CONTROL"
                                color: Theme.muted
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(8)
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: scanner
                x: -64
                y: 0
                width: 64
                height: 2
                color: Theme.telemetry
                opacity: 0.72

                transform: Translate {
                    id: operationsScannerShift

                    SequentialAnimation on x {
                        objectName: "operationsScannerAnimation"
                        running: operationsShell.visible
                        loops: Animation.Infinite
                        NumberAnimation { from: 0; to: operations.width + 128; duration: 4200; easing.type: Theme.easeAmbient }
                        PauseAnimation { duration: 1400 }
                    }
                }
            }
        }
    }

    ArchiveShell {
        id: archiveShell
        anchors.fill: parent
        bridge: AppBridge
        visible: AppBridge.themeShell === "archive"
        enabled: visible
        onAddRequested: toolEditor.openWith("add", AppBridge.newToolDraft())
        onImportRequested: importDialog.open()
        onEditRequested: toolEditor.openWith("edit", AppBridge.selectedToolDraft())
        onStopAllRequested: {
            if (AppBridge.toolModel.runningCount > 0)
                confirmPanel.ask("stop-all", "停止全部活动单元", "将向当前所有活动进程组发送停止指令。", "停止全部", "danger")
            else
                toast.show("当前没有活动单元", "warning")
        }
        onExitRequested: confirmPanel.ask("exit", "退出晶格中枢", "活动工具不会自动停止；仅退出 Lattice 控制界面。", "退出", "danger")
        onSettingsRequested: settingsPanel.opened ? settingsPanel.close() : settingsPanel.open()
    }

    Popup {
        id: settingsPanel
        objectName: "startupSettingsPanel"
        parent: Overlay.overlay
        x: rail.width + 10
        y: 88
        width: Math.min(430, root.width - rail.width - 28)
        height: Math.min(600, root.height - 112)
        padding: 0
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.paperRaised; border.width: Theme.lineWidth; border.color: Theme.ink; radius: 0 }
        contentItem: ColumnLayout {
            spacing: 0
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 54
                color: Theme.ink
                Text { anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter; text: "INTERFACE SETTINGS"; color: Theme.white; font.family: Theme.mono; font.pixelSize: Theme.sp(10); font.weight: Font.Bold }
            }
            ScrollView {
                id: settingsScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    width: Math.max(0, settingsScroll.availableWidth - 32)
                    x: 16
                    y: 16
                    spacing: 13
                    Text { text: "界面主题"; color: Theme.text; font.family: Theme.condensed; font.pixelSize: Theme.sp(22); font.weight: Font.Bold }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        ComboBox {
                            id: themeSelector
                            objectName: "themeSelector"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 38
                            model: AppBridge.availableThemes
                            textRole: "name"
                            valueRole: "id"
                            currentIndex: AppBridge.themeIndex
                            hoverEnabled: true
                            onActivated: AppBridge.setTheme(currentValue)
                            contentItem: Text {
                                leftPadding: 12
                                rightPadding: 38
                                text: themeSelector.displayText
                                color: Theme.text
                                font.family: Theme.sans
                                font.pixelSize: Theme.sp(12)
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                            indicator: VectorIcon {
                                name: "collapse"
                                width: 24
                                height: 24
                                x: themeSelector.width - width - 8
                                y: (themeSelector.height - height) / 2
                                color: Theme.muted
                            }
                            background: Rectangle {
                                color: themeSelector.pressed ? Theme.fog : Theme.paper
                                border.width: Theme.lineWidth
                                border.color: themeSelector.activeFocus ? Theme.command : Theme.line
                                radius: Theme.radiusSmall
                            }
                        }
                        ActionButton { iconName: "folder"; tip: "打开用户主题目录"; onClicked: AppBridge.openThemeDirectory() }
                        ActionButton { iconName: "refresh"; tip: "重新载入主题包"; onClicked: AppBridge.reloadThemes() }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: AppBridge.themeAppearance === "dark" ? "DARK APPEARANCE" : "LIGHT APPEARANCE"
                        color: Theme.faint
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(9)
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                    ColumnLayout {
                        objectName: "fontScaleSection"
                        Layout.fillWidth: true
                        spacing: 12

                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "界面缩放"; color: Theme.text; font.family: Theme.condensed; font.pixelSize: Theme.sp(22); font.weight: Font.Bold }
                            Item { Layout.fillWidth: true }
                            Text {
                                id: fontScaleValue
                                objectName: "fontScaleValue"
                                text: Math.round(AppBridge.fontScale * 100) + "%"
                                color: Theme.telemetry
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(13)
                                font.weight: Font.Bold
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 9

                            ActionButton {
                                objectName: "fontScaleDecrease"
                                iconName: "minus"
                                tip: "减小字号"
                                onClicked: AppBridge.setFontScale(AppBridge.fontScale - 0.05)
                            }
                            Slider {
                                id: fontScaleSlider
                                objectName: "fontScaleSlider"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                from: 0.80
                                to: 1.50
                                stepSize: 0.01
                                value: AppBridge.fontScale
                                snapMode: Slider.SnapAlways
                                live: true
                                Accessible.name: "界面字号"
                                onMoved: AppBridge.setFontScale(value)

                                background: Rectangle {
                                    x: fontScaleSlider.leftPadding
                                    y: fontScaleSlider.topPadding + fontScaleSlider.availableHeight / 2 - height / 2
                                    width: fontScaleSlider.availableWidth
                                    height: 4
                                    color: Theme.line

                                    Rectangle {
                                        width: fontScaleSlider.visualPosition * parent.width
                                        height: parent.height
                                        color: Theme.command
                                    }
                                }
                                handle: Rectangle {
                                    x: fontScaleSlider.leftPadding + fontScaleSlider.visualPosition * (fontScaleSlider.availableWidth - width)
                                    y: fontScaleSlider.topPadding + fontScaleSlider.availableHeight / 2 - height / 2
                                    implicitWidth: 14
                                    implicitHeight: 22
                                    color: fontScaleSlider.pressed ? Theme.command : Theme.ink
                                    border.width: Theme.lineWidth
                                    border.color: Theme.paperRaised
                                    radius: Theme.radiusTiny
                                }
                            }
                            ActionButton {
                                objectName: "fontScaleIncrease"
                                iconName: "plus"
                                tip: "增大字号"
                                onClicked: AppBridge.setFontScale(AppBridge.fontScale + 0.05)
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "80%"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(9) }
                            Item { Layout.fillWidth: true }
                            ActionButton {
                                objectName: "fontScaleReset"
                                iconName: "refresh"
                                label: "100%"
                                tip: "恢复默认字号"
                                onClicked: AppBridge.setFontScale(1.0)
                            }
                            Item { Layout.fillWidth: true }
                            Text { text: "150%"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(9) }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                    Text { text: "启动动画"; color: Theme.text; font.family: Theme.condensed; font.pixelSize: Theme.sp(22); font.weight: Font.Bold }
                    Repeater {
                        model: [
                            { key: "daily", label: "每日首次" },
                            { key: "always", label: "每次启动" },
                            { key: "off", label: "关闭" }
                        ]
                        Button {
                            id: startupModeButton
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 36
                            text: modelData.label
                            hoverEnabled: true
                            onClicked: AppBridge.setStartupMode(startupModeButton.modelData.key)
                            transform: Translate {
                                y: startupModeButton.down ? 1 : 0
                                Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                            }
                            contentItem: Text { text: startupModeButton.text; color: AppBridge.startupMode === startupModeButton.modelData.key ? Theme.white : Theme.text; font.family: Theme.sans; font.pixelSize: Theme.sp(12); horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            background: Rectangle {
                                color: AppBridge.startupMode === startupModeButton.modelData.key ? Theme.ink : startupModeButton.hovered ? Theme.fog : Theme.paper
                                border.width: Theme.lineWidth
                                border.color: AppBridge.startupMode === startupModeButton.modelData.key ? Theme.ink : Theme.line
                                radius: 0

                                Behavior on color { ColorAnimation { duration: Theme.fast } }
                                Behavior on border.color { ColorAnimation { duration: Theme.fast } }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ActionButton { iconName: "play"; label: "立即预览"; kind: "command"; onClicked: { AppBridge.previewStartup(); startupExperience.show(true) } }
                        ActionButton { iconName: "clear"; label: "清理缓存"; onClicked: AppBridge.clearStartupCache() }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                    Text { text: "版权与安全"; color: Theme.text; font.family: Theme.mono; font.pixelSize: Theme.sp(10); font.weight: Font.Bold }
                    Text {
                        Layout.fillWidth: true
                        text: "Lattice 是非官方项目，与《明日方舟》、鹰角网络或 Yostar 无隶属、赞助或背书关系。代码以 MIT 发布，但不授予任何角色、商标、台词、剧情文本或官方图片的再许可。启动页只从清单白名单中的官方 HTTPS 来源下载可选图片到本地缓存；失败时使用内置抽象背景。程序不上传缓存、不收集遥测。权利人可通过 GitHub 仓库 issue 或 release 联系渠道要求更正或下架。"
                        color: Theme.muted
                        font.family: Theme.sans
                        font.pixelSize: Theme.sp(12)
                        lineHeight: 1.35
                        wrapMode: Text.Wrap
                    }
                    Item { Layout.fillWidth: true; Layout.preferredHeight: 16 }
                }
            }
        }

        enter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
                NumberAnimation { property: "scale"; from: 0.985; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
            }
        }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fast; easing.type: Theme.easeExit } }
    }

    StartupExperience {
        id: startupExperience
        objectName: "startupExperience"
        bridge: AppBridge
    }

    Connections {
        target: AppBridge

        function onSelectionIdentityChanged() { root.revealOperationsSelection() }
        function onThemeChanged() { root.syncTheme() }
        function onToastRequested(message, kind) { toast.show(message, kind) }
        function onDialogRequested(title, message, kind) {
            noticeTitle.text = title
            noticeMessage.text = message
            noticeStripe.color = kind === "error" ? Theme.danger : kind === "warning" ? Theme.warning : Theme.telemetry
            noticeDialog.open()
        }
        function onEditorRequested(mode, draft) { toolEditor.openWith(mode, draft) }
        function onImportOverwriteRequested(path, id, name) {
            root.pendingImportPath = path
            confirmPanel.ask("overwrite-import", "覆盖已有配置", name + " / " + id + " 已存在。覆盖当前配置文件？", "覆盖", "danger")
        }
    }

    EditorPanel {
        id: toolEditor
        bridge: AppBridge
        onDeleteRequested: confirmPanel.ask("delete", "删除工具配置", root.value("name", "当前工具") + " 的配置将被移除，磁盘日志会保留。", "删除", "danger")
    }

    ConfirmPanel {
        id: confirmPanel
        onConfirmed: function(code) {
            if (code === "stop-all") AppBridge.stopAll()
            else if (code === "delete") AppBridge.deleteSelected()
            else if (code === "overwrite-import") AppBridge.confirmImportOverwrite(root.pendingImportPath)
            else if (code === "exit") AppBridge.requestExit()
        }
    }

    Popup {
        id: noticeDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(500, parent.width - 48)
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape
        Overlay.modal: Rectangle { color: Theme.scrim }
        background: Rectangle { color: Theme.paperRaised; border.width: Theme.lineWidth; border.color: Theme.ink; radius: Theme.radiusSmall }
        contentItem: ColumnLayout {
            spacing: 0
            Rectangle { id: noticeStripe; Layout.fillWidth: true; Layout.preferredHeight: 7; color: Theme.danger }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: 24
                spacing: 13
                Text { id: noticeTitle; color: Theme.text; font.family: Theme.condensed; font.pixelSize: Theme.sp(24); font.weight: Font.Bold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Text { id: noticeMessage; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(12); lineHeight: 1.35; wrapMode: Text.Wrap; Layout.fillWidth: true }
                ActionButton { label: "确认"; kind: "command"; Layout.alignment: Qt.AlignRight; onClicked: noticeDialog.close() }
            }
        }

        enter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
                NumberAnimation { property: "scale"; from: 0.965; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
            }
        }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fast; easing.type: Theme.easeExit } }
    }

    Platform.FileDialog {
        id: importDialog
        title: "导入工具或配置"
        nameFilters: ["工具配置、程序、脚本或本机程序 (*.toml *.exe *.bat *.cmd *.ps1 *.py *.sh *)", "所有文件 (*)"]
        onAccepted: AppBridge.prepareImport(selectedFile.toString())
    }

    Toast {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - 72
        z: 1000
    }

    Shortcut { sequence: "Ctrl+K"; onActivated: AppBridge.themeShell === "archive" ? archiveShell.focusSearch() : searchField.forceActiveFocus() }
    Shortcut { sequence: "Ctrl+N"; onActivated: toolEditor.openWith("add", AppBridge.newToolDraft()) }
    Shortcut { sequence: "F2"; enabled: root.hasSelection; onActivated: toolEditor.openWith("edit", AppBridge.selectedToolDraft()) }
    Shortcut { sequence: "Alt+R"; enabled: root.hasSelection; onActivated: AppBridge.restartSelected() }
    Shortcut { sequence: "Ctrl+Return"; enabled: root.hasSelection; onActivated: AppBridge.startSelected() }
    Shortcut { sequence: "Shift+R"; onActivated: AppBridge.reloadTools(true) }
    Shortcut { sequence: "Ctrl+="; onActivated: AppBridge.setFontScale(AppBridge.fontScale + 0.05) }
    Shortcut { sequence: "Ctrl+-"; onActivated: AppBridge.setFontScale(AppBridge.fontScale - 0.05) }
    Shortcut { sequence: "Ctrl+0"; onActivated: AppBridge.setFontScale(1.0) }
}
