pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Item {
    id: shell
    objectName: "archiveShell"

    property var bridge
    property real splitRatio: 0.60
    property int dossierTab: 0
    property int dropTargetRow: -1
    property real dropTargetY: -1
    property string draggingLabel: ""
    property string clockDate: "---- -- --"
    property string clockTime: "--:--:--"
    property var cpuHistory: []
    property var memoryHistory: []
    property var gpuHistory: []
    property var previousCpuHistory: []
    property var previousMemoryHistory: []
    property var previousGpuHistory: []
    property int lastTelemetrySequence: -1
    property real pendingSplitRatio: 0.60
    property bool splitInitialized: false
    property bool componentReady: false
    property real traceProgress: 1
    property real dossierSelectionReveal: 1
    property real dossierTabReveal: 1
    property int dossierTabDirection: 1
    readonly property int telemetryHistoryLimit: 42

    readonly property bool hasSelection: bridge && bridge.selectedId.length > 0
    readonly property var selectedData: bridge ? bridge.selected : ({})
    readonly property bool showOptionalCommands: width >= 1120
    readonly property real minimumSplitRatio: {
        var available = workspace.usableWidth
        if (available <= 0)
            return 0.50
        var minimum = Math.max(0.20, 400 / available)
        var maximum = Math.min(0.80, (available - 400) / available)
        return minimum <= maximum ? minimum : 0.50
    }
    readonly property real maximumSplitRatio: {
        var available = workspace.usableWidth
        if (available <= 0)
            return 0.50
        var minimum = Math.max(0.20, 400 / available)
        var maximum = Math.min(0.80, (available - 400) / available)
        return minimum <= maximum ? maximum : 0.50
    }

    signal addRequested()
    signal importRequested()
    signal editRequested()
    signal stopAllRequested()
    signal exitRequested()
    signal settingsRequested()
    signal fontScaleRequested()

    function value(key, fallback) {
        var current = selectedData ? selectedData[key] : undefined
        return current === undefined || current === null ? fallback : current
    }

    function twoDigits(value) {
        return String(value).padStart(2, "0")
    }

    function updateClock() {
        var now = new Date()
        clockDate = now.getFullYear() + "-" + twoDigits(now.getMonth() + 1) + "-" + twoDigits(now.getDate())
        clockTime = twoDigits(now.getHours()) + ":" + twoDigits(now.getMinutes()) + ":" + twoDigits(now.getSeconds())
    }

    function appendMetric(history, value) {
        if (typeof value !== "number" || !isFinite(value) || value < 0)
            return history
        var normalized = Math.max(0, Math.min(1, value / 100))
        if (history.length === 0) {
            var initial = []
            for (var index = 0; index < telemetryHistoryLimit; ++index)
                initial.push(normalized)
            return initial
        }
        var next = history.slice(Math.max(0, history.length - (telemetryHistoryLimit - 1)))
        next.push(normalized)
        return next
    }

    function appendTelemetry() {
        if (!bridge)
            return
        var sequence = Number(bridge.telemetry.sampleSequence)
        if (!isFinite(sequence) || sequence <= 0 || sequence === lastTelemetrySequence)
            return
        lastTelemetrySequence = sequence
        previousCpuHistory = cpuHistory.slice()
        previousMemoryHistory = memoryHistory.slice()
        previousGpuHistory = gpuHistory.slice()
        cpuHistory = appendMetric(cpuHistory, Number(bridge.telemetry.cpuValue))
        memoryHistory = appendMetric(memoryHistory, Number(bridge.telemetry.memoryValue))
        gpuHistory = appendMetric(gpuHistory, Number(bridge.telemetry.gpuValue))
        if (visible)
            telemetryTraceAnimation.restart()
        else {
            traceProgress = 1
            telemetryTrace.requestPaint()
        }
    }

    function revealDossierSelection() {
        if (!visible) {
            dossierSelectionReveal = 1
            return
        }
        dossierSelectionAnimation.restart()
    }

    function revealDossierTab() {
        if (!visible) {
            dossierTabReveal = 1
            return
        }
        dossierTabDirection = dossierTab === 0 ? -1 : 1
        dossierTabAnimation.restart()
    }

    function clampSplitRatio(value) {
        return Math.max(minimumSplitRatio, Math.min(maximumSplitRatio, value))
    }

    function queueSplitRatio(value) {
        pendingSplitRatio = clampSplitRatio(value)
        if (!splitFrame.running)
            splitFrame.start()
    }

    function applyPendingSplit() {
        splitFrame.stop()
        splitRatio = clampSplitRatio(pendingSplitRatio)
    }

    function logAccent(level) {
        if (level === "command") return Theme.command
        if (level === "warn") return Theme.warning
        if (level === "error") return Theme.danger
        return Theme.telemetry
    }

    function focusSearch() {
        archiveSearch.forceActiveFocus()
    }

    function groupCode(index) {
        return "GRP-" + twoDigits(Number(index) + 1)
    }

    onDossierTabChanged: {
        if (componentReady)
            revealDossierTab()
    }
    onTraceProgressChanged: {
        if (componentReady)
            telemetryTrace.requestPaint()
    }
    onVisibleChanged: {
        if (!componentReady)
            return
        if (visible) {
            appendTelemetry()
            revealDossierSelection()
        } else {
            telemetryTraceAnimation.stop()
            dossierSelectionAnimation.stop()
            dossierTabAnimation.stop()
            traceProgress = 1
            dossierSelectionReveal = 1
            dossierTabReveal = 1
        }
    }

    function updateDropTarget(y) {
        if (!bridge || !bridge.reorderingAllowed)
            return
        var row = archiveList.indexAt(8, y)
        if (row < 0)
            row = bridge.toolModel.rowCount() - 1
        dropTargetRow = row
        var target = archiveList.itemAtIndex(row)
        dropTargetY = target ? target.y + (y > target.y + target.height / 2 ? target.height : 0) : y
    }

    function commitDrop(sourceKind, sourceGroup, sourceTool, y) {
        if (!bridge || !bridge.reorderingAllowed)
            return
        updateDropTarget(y)
        var targetRow = bridge.toolModel.getRow(dropTargetRow)
        if (!targetRow || !targetRow.rowType)
            return
        if (sourceKind === "group") {
            var groupIndex = Number(targetRow.groupIndex)
            if (targetRow.rowType === "group" && y > dropTargetY)
                groupIndex += 1
            bridge.moveGroup(sourceGroup, groupIndex)
            return
        }
        var targetGroup = targetRow.groupKey
        var targetIndex = targetRow.rowType === "group" ? Number(targetRow.groupToolCount) : Number(targetRow.toolIndex)
        if (targetRow.rowType === "tool" && y > dropTargetY)
            targetIndex += 1
        bridge.moveTool(sourceTool, targetGroup, targetIndex)
    }

    Component.onCompleted: {
        componentReady = true
        updateClock()
        if (visible)
            appendTelemetry()
    }

    Timer {
        interval: 1000
        running: shell.visible
        repeat: true
        onTriggered: shell.updateClock()
    }

    NumberAnimation {
        id: telemetryTraceAnimation
        objectName: "archiveTelemetryAnimation"
        target: shell
        property: "traceProgress"
        from: 0
        to: 1
        duration: Theme.slow
        easing.type: Theme.easeStandard
    }

    NumberAnimation {
        id: dossierSelectionAnimation
        objectName: "archiveSelectionAnimation"
        target: shell
        property: "dossierSelectionReveal"
        from: 0
        to: 1
        duration: Theme.normal
        easing.type: Theme.easeEnter
    }

    NumberAnimation {
        id: dossierTabAnimation
        objectName: "archiveTabAnimation"
        target: shell
        property: "dossierTabReveal"
        from: 0
        to: 1
        duration: Theme.normal
        easing.type: Theme.easeEnter
    }

    Timer {
        id: splitFrame
        interval: 16
        repeat: false
        onTriggered: shell.splitRatio = shell.clampSplitRatio(shell.pendingSplitRatio)
    }

    Timer {
        interval: 0
        running: true
        repeat: false
        onTriggered: {
            shell.splitInitialized = true
            shell.pendingSplitRatio = shell.clampSplitRatio(0.60)
            shell.splitRatio = shell.pendingSplitRatio
        }
    }

    Connections {
        target: shell.bridge
        ignoreUnknownSignals: true

        function onTelemetryChanged() {
            if (shell.visible)
                shell.appendTelemetry()
        }
        function onSelectionIdentityChanged() {
            var tabWasAlreadySelected = shell.dossierTab === 0
            shell.dossierTab = 0
            if (tabWasAlreadySelected)
                shell.revealDossierTab()
            shell.revealDossierSelection()
        }
    }

    ColumnLayout {
        objectName: "archiveRootLayout"
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: identityBand
            objectName: "archiveIdentityBand"
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            color: Theme.ink

            RowLayout {
                objectName: "archiveIdentityLayout"
                anchors.fill: parent
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 350
                    Layout.fillHeight: true

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: shell.width < 1160 ? 18 : 24
                        anchors.rightMargin: 18
                        spacing: 18

                        Item {
                            Layout.preferredWidth: 54
                            Layout.preferredHeight: 54

                            Rectangle {
                                anchors.fill: parent
                                color: "transparent"
                                border.width: Theme.lineWidth
                                border.color: Theme.lineDark
                            }
                            Rectangle { x: 7; y: -1; width: 14; height: 3; color: Theme.command }
                            Rectangle { anchors.right: parent.right; anchors.rightMargin: -1; anchors.bottom: parent.bottom; anchors.bottomMargin: 7; width: 3; height: 14; color: Theme.command }
                            Text {
                                anchors.centerIn: parent
                                text: shell.bridge ? shell.twoDigits(shell.bridge.toolModel.totalCount) : "00"
                                color: Theme.warning
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(18)
                                font.weight: Font.Bold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                text: "LOCAL PROCESS CONTROL / OPERATIONS ARCHIVE"
                                color: Theme.mutedOnDark
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(8)
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 14
                                Text {
                                    text: "LATTICE"
                                    color: Theme.white
                                    font.family: Theme.condensed
                                    font.pixelSize: Theme.sp(shell.width < 1120 ? 28 : 31)
                                    font.weight: Font.Black
                                }
                                Text {
                                    text: "晶格中枢"
                                    color: Theme.mutedOnDark
                                    font.family: Theme.sans
                                    font.pixelSize: Theme.sp(15)
                                    font.weight: Font.Medium
                                }
                                Item { Layout.fillWidth: true }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: shell.clockDate + " / " + shell.clockTime + " / DESKTOP NODE"
                                color: Theme.faintOnDark
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(8)
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.lineDark }
                }

                RowLayout {
                    Layout.preferredWidth: Math.max(340, Math.min(700, shell.width * 0.34))
                    Layout.minimumWidth: 340
                    Layout.maximumWidth: 700
                    Layout.fillHeight: true
                    spacing: 0

                    Repeater {
                        model: [
                            { value: shell.bridge ? shell.bridge.toolModel.totalCount : 0, label: "REGISTERED UNITS", color: Theme.white },
                            { value: shell.bridge ? shell.bridge.toolModel.runningCount : 0, label: "ACTIVE PROCESSES", color: Theme.telemetry },
                            { value: shell.bridge ? shell.bridge.toolModel.exitedCount : 0, label: "ATTENTION REQUIRED", color: Theme.danger }
                        ]

                        Item {
                            id: summaryCell
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.fillHeight: true

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: shell.width < 1100 ? 11 : 16
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 7

                                Text {
                                    id: summaryValue
                                    text: shell.twoDigits(summaryCell.modelData.value)
                                    color: summaryCell.modelData.color
                                    font.family: Theme.mono
                                    font.pixelSize: Theme.sp(21)
                                    font.weight: Font.Bold
                                    onTextChanged: summaryPulse.restart()
                                }
                                Text {
                                    text: summaryCell.modelData.label
                                    color: Theme.faintOnDark
                                    font.family: Theme.mono
                                    font.pixelSize: Theme.sp(7)
                                    font.weight: Font.DemiBold
                                }
                            }
                            SequentialAnimation {
                                id: summaryPulse
                                NumberAnimation { target: summaryValue; property: "opacity"; from: 0.46; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
                            }
                            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.lineDark }
                        }
                    }
                }

                Item {
                    id: globalActionsCell
                    objectName: "archiveGlobalActionsCell"
                    Layout.preferredWidth: globalActions.implicitWidth + 24
                    Layout.fillHeight: true

                    Row {
                        id: globalActions
                        objectName: "archiveGlobalActions"
                        anchors.centerIn: parent
                        spacing: 6

                        ArchiveIconButton { anchors.verticalCenter: parent.verticalCenter; iconName: "plus"; kind: "dark"; tip: "添加工具"; onClicked: shell.addRequested() }
                        ArchiveIconButton { anchors.verticalCenter: parent.verticalCenter; iconName: "upload"; kind: "dark"; tip: "导入工具或配置"; onClicked: shell.importRequested() }
                        ArchiveIconButton { visible: shell.showOptionalCommands; anchors.verticalCenter: parent.verticalCenter; iconName: "refresh"; kind: "dark"; tip: "重载配置索引"; onClicked: shell.bridge.reloadTools(true) }
                        ArchiveIconButton { visible: shell.showOptionalCommands; anchors.verticalCenter: parent.verticalCenter; iconName: "folder"; kind: "dark"; tip: "打开配置目录"; onClicked: shell.bridge.openConfigDirectory() }
                        ArchiveIconButton { anchors.verticalCenter: parent.verticalCenter; iconName: "settings"; kind: "dark"; tip: "主题与启动设置"; onClicked: shell.settingsRequested() }
                        Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 1; height: 32; color: Theme.lineDark }
                        ArchiveIconButton { anchors.verticalCenter: parent.verticalCenter; iconName: "power"; kind: "darkDanger"; tip: "停止全部活动工具"; onClicked: shell.stopAllRequested() }
                    }
                }
            }

            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 4; color: Theme.command }
        }

        Rectangle {
            id: evidenceBand
            objectName: "archiveEvidenceBand"
            Layout.fillWidth: true
            Layout.preferredHeight: 74
            color: Theme.fog

            RowLayout {
                objectName: "archiveEvidenceLayout"
                anchors.fill: parent
                spacing: 0

                Item {
                    Layout.preferredWidth: shell.width < 1260 ? 190 : 210
                    Layout.fillHeight: true

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 18
                        anchors.rightMargin: 12
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            color: "transparent"
                            border.width: Theme.lineWidth
                            border.color: Theme.telemetry
                            Text { anchors.centerIn: parent; text: "LN"; color: Theme.telemetryDark; font.family: Theme.mono; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 5
                            RowLayout {
                                spacing: 7
                                Rectangle {
                                    Layout.preferredWidth: 6
                                    Layout.preferredHeight: 6
                                    color: shell.bridge && shell.bridge.telemetry.state === "OFFLINE" ? Theme.danger : shell.bridge && shell.bridge.telemetry.state === "PAUSED" ? Theme.warning : Theme.telemetry
                                }
                                Text {
                                    text: shell.bridge ? shell.bridge.telemetry.stateLabel : "未连接"
                                    color: Theme.text
                                    font.family: Theme.sans
                                    font.pixelSize: Theme.sp(10)
                                    font.weight: Font.DemiBold
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "LOCAL / " + (shell.bridge ? shell.bridge.telemetry.updated : "--:--:--")
                                color: Theme.faint
                                font.family: Theme.mono
                                font.pixelSize: Theme.sp(7)
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                ArchiveMetricCell {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    label: "CPU / PROCESSOR"
                    valueText: shell.bridge ? shell.bridge.telemetry.cpuText : "--"
                    detailText: shell.bridge ? shell.bridge.telemetry.cpuDetail : ""
                    percent: shell.bridge ? shell.bridge.telemetry.cpuValue : -1
                }
                ArchiveMetricCell {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    label: "MEMORY / HOST"
                    valueText: shell.bridge ? shell.bridge.telemetry.memoryText : "--"
                    detailText: shell.bridge ? shell.bridge.telemetry.memoryDetail : ""
                    percent: shell.bridge ? shell.bridge.telemetry.memoryValue : -1
                }
                ArchiveMetricCell {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    label: "GPU / COMPUTE"
                    valueText: shell.bridge ? shell.bridge.telemetry.gpuText : "--"
                    detailText: shell.bridge ? shell.bridge.telemetry.gpuDetail : ""
                    percent: shell.bridge ? shell.bridge.telemetry.gpuValue : -1
                }

                Item {
                    Layout.preferredWidth: Math.max(300, shell.width * 0.39)
                    Layout.fillHeight: true

                    Rectangle { anchors.left: parent.left; width: 1; height: parent.height; color: Theme.line }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.top: parent.top
                        anchors.topMargin: 8
                        text: "SYSTEM EVIDENCE / " + Math.max(shell.cpuHistory.length, shell.memoryHistory.length, shell.gpuHistory.length) + " SAMPLES"
                        color: Theme.muted
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(7)
                        font.weight: Font.DemiBold
                    }
                    Item {
                        id: telemetryPlot
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.right: sampleToggle.left
                        anchors.rightMargin: 10
                        anchors.top: parent.top
                        anchors.topMargin: 20
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 8

                        onWidthChanged: {
                            telemetryGrid.requestPaint()
                            telemetryTrace.requestPaint()
                        }
                        onHeightChanged: {
                            telemetryGrid.requestPaint()
                            telemetryTrace.requestPaint()
                        }

                        Canvas {
                            id: telemetryGrid
                            anchors.fill: parent
                            antialiasing: false

                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.reset()
                                if (width <= 1 || height <= 1)
                                    return
                                ctx.lineWidth = 1
                                ctx.strokeStyle = Theme.line
                                for (var gx = 0.5; gx < width; gx += 36) {
                                    ctx.beginPath()
                                    ctx.moveTo(gx, 0)
                                    ctx.lineTo(gx, height)
                                    ctx.stroke()
                                }
                                for (var gy = 0.5; gy < height; gy += 14) {
                                    ctx.beginPath()
                                    ctx.moveTo(0, gy)
                                    ctx.lineTo(width, gy)
                                    ctx.stroke()
                                }
                            }
                        }

                        Canvas {
                            id: telemetryTrace
                            objectName: "archiveTelemetryTrace"
                            anchors.fill: parent
                            antialiasing: true

                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.reset()
                                if (width <= 1 || height <= 1)
                                    return

                                function sourceValue(previous, points, index) {
                                    if (previous.length === 0)
                                        return points[index]
                                    var sourceIndex = index - Math.max(0, points.length - previous.length)
                                    if (sourceIndex < 0)
                                        return previous[0]
                                    return previous[Math.min(previous.length - 1, sourceIndex)]
                                }

                                function draw(previous, values, currentValue, color, traceWidth) {
                                    var normalized = Number(currentValue)
                                    if (values.length === 0 && (!isFinite(normalized) || normalized < 0))
                                        return
                                    var points = values.length > 0 ? values : [normalized, normalized]
                                    if (points.length === 1)
                                        points = [points[0], points[0]]
                                    var lastY = 0
                                    ctx.strokeStyle = color
                                    ctx.lineWidth = traceWidth
                                    ctx.beginPath()
                                    for (var index = 0; index < points.length; ++index) {
                                        var startValue = sourceValue(previous, points, index)
                                        var value = startValue + (points[index] - startValue) * shell.traceProgress
                                        var x = index * width / (points.length - 1)
                                        var y = height - Math.max(0, Math.min(1, value)) * (height - 4) - 2
                                        lastY = y
                                        if (index === 0) ctx.moveTo(x, y)
                                        else ctx.lineTo(x, y)
                                    }
                                    ctx.stroke()
                                    ctx.fillStyle = color
                                    ctx.fillRect(width - 2, lastY - 1.5, 3, 3)
                                }

                                draw(shell.previousCpuHistory, shell.cpuHistory, shell.bridge ? shell.bridge.telemetry.cpuValue / 100 : -1, Theme.command, 1.6)
                                draw(shell.previousMemoryHistory, shell.memoryHistory, shell.bridge ? shell.bridge.telemetry.memoryValue / 100 : -1, Theme.telemetry, 1.6)
                                draw(shell.previousGpuHistory, shell.gpuHistory, shell.bridge ? shell.bridge.telemetry.gpuValue / 100 : -1, Theme.text, 1.0)
                            }
                        }

                        Rectangle {
                            x: Math.round((parent.width - width) * shell.traceProgress)
                            width: 1
                            height: parent.height
                            color: Theme.telemetry
                            opacity: telemetryTraceAnimation.running ? 0.42 : 0

                            Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                        }

                        Connections {
                            target: Theme
                            function onLineChanged() { telemetryGrid.requestPaint() }
                            function onCommandChanged() { telemetryTrace.requestPaint() }
                            function onTelemetryChanged() { telemetryTrace.requestPaint() }
                            function onTextChanged() { telemetryTrace.requestPaint() }
                        }
                    }
                    ArchiveIconButton {
                        id: sampleToggle
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        iconName: shell.bridge && shell.bridge.hardwarePaused ? "play" : "pause"
                        kind: "neutral"
                        tip: shell.bridge && shell.bridge.hardwarePaused ? "恢复系统采样" : "暂停系统采样"
                        onClicked: shell.bridge.setHardwarePaused(!shell.bridge.hardwarePaused)
                    }
                }
            }

            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
        }

        Item {
            id: workspace
            objectName: "archiveWorkspace"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            readonly property real usableWidth: Math.max(0, width - splitter.width)
            onUsableWidthChanged: {
                if (shell.splitInitialized && usableWidth >= 800) {
                    shell.pendingSplitRatio = shell.clampSplitRatio(shell.splitRatio)
                    shell.splitRatio = shell.pendingSplitRatio
                }
            }

            Rectangle {
                id: matrixPanel
                objectName: "archiveMatrix"
                x: 0
                y: 0
                width: Math.round(workspace.usableWidth * shell.splitRatio)
                height: workspace.height
                color: Theme.paper
                clip: true

                readonly property bool showGroup: width > 640
                readonly property bool showUptime: width > 700
                readonly property bool showAutostart: width > 820
                readonly property real seqWidth: width <= 480 ? 34 : width <= 700 ? 38 : width <= 820 ? 40 : 42
                readonly property real identityWidth: width <= 480 ? 110 : width <= 640 ? 135 : width <= 700 ? 145 : width <= 820 ? 150 : 160
                readonly property real groupWidth: width <= 700 ? 78 : width <= 820 ? 82 : 94
                readonly property real stateWidth: width <= 480 ? 70 : width <= 640 ? 78 : width <= 700 ? 82 : width <= 820 ? 86 : 92
                readonly property real pidWidth: width <= 480 ? 50 : width <= 700 ? 58 : width <= 820 ? 62 : 68
                readonly property real uptimeWidth: width <= 820 ? 76 : 82
                readonly property real cwdWidth: width <= 480 ? 90 : width <= 640 ? 120 : width <= 820 ? 125 : 160
                readonly property real autostartWidth: 86
                readonly property real dragWidth: width <= 480 ? 28 : width <= 700 ? 32 : width <= 820 ? 34 : 38

                Rectangle {
                    id: queryBand
                    width: parent.width
                    height: matrixPanel.width <= 640 ? 92 : 49
                    color: Theme.paperRaised

                    readonly property real edgePadding: matrixPanel.width <= 820 ? 12 : 18
                    readonly property real itemGap: matrixPanel.width <= 820 ? 8 : 14
                    readonly property real filterWidth: matrixPanel.width <= 700 ? 200 : matrixPanel.width <= 820 ? 208 : 288
                    readonly property real summaryWidth: matrixPanel.width <= 820 ? 108 : 130
                    readonly property bool stacked: matrixPanel.width <= 640
                    readonly property real availableSearchWidth: width - edgePadding * 2 - filterWidth - summaryWidth - itemGap * 2

                    TextField {
                        id: archiveSearch
                        objectName: "archiveToolSearch"
                        x: queryBand.edgePadding
                        y: queryBand.stacked ? 8 : 7
                        width: queryBand.stacked
                            ? queryBand.width - queryBand.edgePadding * 2
                            : Math.min(430, Math.max(170, queryBand.availableSearchWidth))
                        height: 34
                        text: shell.bridge ? shell.bridge.searchText : ""
                        placeholderText: "搜索名称、ID、路径或分组"
                        leftPadding: 34
                        rightPadding: 12
                        selectByMouse: true
                        color: Theme.text
                        font.family: Theme.sans
                        font.pixelSize: Theme.sp(11)
                        onTextEdited: shell.bridge.setSearchText(text)
                        background: Rectangle {
                            color: Theme.paper
                            border.width: Theme.lineWidth
                            border.color: archiveSearch.activeFocus ? Theme.command : Theme.line
                            radius: Theme.radiusSmall
                        }
                        VectorIcon { anchors.left: parent.left; anchors.leftMargin: 9; anchors.verticalCenter: parent.verticalCenter; name: "search"; color: Theme.muted; width: 15; height: 15 }
                    }

                    Row {
                        id: filterControl
                        x: queryBand.stacked
                            ? queryBand.edgePadding
                            : queryBand.width - queryBand.edgePadding - queryBand.summaryWidth - queryBand.itemGap - width
                        y: queryBand.stacked ? 50 : 7
                        width: queryBand.filterWidth
                        height: 34
                        spacing: 0

                        Repeater {
                            model: [
                                { key: "all", label: "全部", count: shell.bridge ? shell.bridge.toolModel.totalCount : 0 },
                                { key: "running", label: "活动", count: shell.bridge ? shell.bridge.toolModel.runningCount : 0 },
                                { key: "stopped", label: "静止", count: shell.bridge ? shell.bridge.toolModel.idleCount : 0 },
                                { key: "exited", label: "异常", count: shell.bridge ? shell.bridge.toolModel.exitedCount : 0 }
                            ]

                            Button {
                                id: filterButton
                                required property var modelData
                                width: filterControl.width / 4
                                height: filterControl.height
                                hoverEnabled: true
                                text: modelData.label + " " + modelData.count
                                onClicked: shell.bridge.setFilterMode(filterButton.modelData.key)
                                transform: Translate {
                                    y: filterButton.down ? 1 : 0
                                    Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                                }
                                contentItem: Text {
                                    text: filterButton.text
                                    color: shell.bridge && shell.bridge.filterMode === filterButton.modelData.key ? Theme.white : Theme.muted
                                    font.family: Theme.sans
                                    font.pixelSize: Theme.sp(9)
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    color: shell.bridge && shell.bridge.filterMode === filterButton.modelData.key ? Theme.ink : filterButton.hovered ? Theme.fog : Theme.paper
                                    border.width: Theme.lineWidth
                                    border.color: shell.bridge && shell.bridge.filterMode === filterButton.modelData.key ? Theme.ink : Theme.line

                                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                                    Behavior on border.color { ColorAnimation { duration: Theme.fast } }
                                }
                            }
                        }
                    }

                    Text {
                        id: matrixSummary
                        x: queryBand.width - width - queryBand.edgePadding
                        y: queryBand.stacked ? 54 : 10
                        width: queryBand.summaryWidth
                        height: 25
                        text: (shell.bridge ? shell.twoDigits(shell.bridge.toolModel.visibleCount) : "00") + " / VISIBLE  " + (shell.bridge ? shell.twoDigits(shell.bridge.toolModel.groupCount) : "00") + " GROUPS"
                        color: Theme.muted
                        font.family: Theme.mono
                        font.pixelSize: Theme.sp(8)
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                    }

                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                }

                Rectangle {
                    id: matrixHead
                    y: queryBand.height
                    width: parent.width
                    height: 30
                    color: Theme.fog

                    RowLayout {
                        anchors.fill: parent
                        spacing: 0

                        Text { Layout.preferredWidth: matrixPanel.seqWidth; Layout.fillHeight: true; leftPadding: 9; text: "SEQ"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { Layout.fillWidth: true; Layout.preferredWidth: matrixPanel.identityWidth; Layout.fillHeight: true; leftPadding: 10; text: "UNIT / IDENTITY"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { visible: matrixPanel.showGroup; Layout.preferredWidth: matrixPanel.groupWidth; Layout.fillHeight: true; leftPadding: 10; text: "GROUP"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { Layout.preferredWidth: matrixPanel.stateWidth; Layout.fillHeight: true; leftPadding: 10; text: "STATE"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { Layout.preferredWidth: matrixPanel.pidWidth; Layout.fillHeight: true; leftPadding: 10; text: "PID"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { visible: matrixPanel.showUptime; Layout.preferredWidth: matrixPanel.uptimeWidth; Layout.fillHeight: true; leftPadding: 10; text: "UPTIME"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { Layout.fillWidth: true; Layout.preferredWidth: matrixPanel.cwdWidth; Layout.fillHeight: true; leftPadding: 10; text: "WORKING DIRECTORY"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Text { objectName: "archiveAutostartHeader"; visible: matrixPanel.showAutostart; Layout.preferredWidth: matrixPanel.autostartWidth; Layout.fillHeight: true; leftPadding: 10; text: "AUTOSTART"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); verticalAlignment: Text.AlignVCenter }
                        Item { Layout.preferredWidth: matrixPanel.dragWidth; Layout.fillHeight: true }
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.ink }
                }

                ListView {
                    id: archiveList
                    objectName: "archiveToolList"
                    x: 0
                    y: matrixHead.y + matrixHead.height
                    width: parent.width
                    height: parent.height - y
                    model: shell.bridge ? shell.bridge.toolModel : null
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    currentIndex: -1
                    reuseItems: true
                    cacheBuffer: 240

                    delegate: Item {
                        id: rowDelegate
                        required property string rowType
                        required property string groupName
                        required property string groupKey
                        required property bool collapsed
                        required property int groupIndex
                        required property int toolIndex
                        required property int groupToolCount
                        required property string toolId
                        required property string toolName
                        required property string toolCwd
                        required property string toolState
                        required property string stateLabel
                        required property string pidText
                        required property string uptimeText
                        required property string exitCodeText
                        required property string sequenceText
                        required property bool toolAutostart
                        property string rowKind: rowType
                        property string rowGroupName: groupName
                        property string rowGroupKey: groupKey
                        property bool rowCollapsed: Boolean(collapsed)
                        property int rowGroupIndex: groupIndex
                        property int rowToolIndex: toolIndex
                        property int rowGroupToolCount: groupToolCount
                        property bool dragging: false
                        property bool delegateReady: false
                        property real pressX: 0
                        property real pressY: 0
                        readonly property bool selected: rowKind === "tool" && toolId === shell.bridge.selectedId
                        width: ListView.view ? ListView.view.width : archiveList.width
                        height: rowKind === "group" ? 32 : 50
                        z: dragging ? 20 : rowKind === "group" ? 3 : 1
                        opacity: dragging ? 0.45 : 1
                        onToolStateChanged: {
                            if (delegateReady && rowKind === "tool")
                                statePulse.restart()
                        }
                        Component.onCompleted: delegateReady = true

                        Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                        ListView.onPooled: statePulse.stop()
                        ListView.onReused: {
                            statePulse.stop()
                            stateMark.opacity = 1
                            stateMark.scale = 1
                        }

                        Rectangle {
                            anchors.fill: parent
                            color: rowDelegate.rowKind === "group"
                                ? Theme.fog
                                : rowDelegate.selected
                                    ? "#fff4e9"
                                    : rowMouse.containsMouse ? Theme.paperRaised : Theme.paper

                            Behavior on color { ColorAnimation { duration: Theme.fast } }
                        }
                        Rectangle { visible: rowDelegate.rowKind === "group"; anchors.top: parent.top; width: parent.width; height: 1; color: Theme.ink }
                        Rectangle {
                            anchors.top: parent.top
                            width: parent.width
                            height: 2
                            color: Theme.command
                            opacity: rowDelegate.selected ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                        }
                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width
                            height: rowDelegate.selected ? 2 : 1
                            color: rowDelegate.selected ? Theme.command : Theme.line
                            Behavior on color { ColorAnimation { duration: Theme.fast } }
                        }
                        Rectangle {
                            id: selectionRail
                            anchors.left: parent.left
                            width: 5
                            height: parent.height
                            color: Theme.command
                            opacity: rowDelegate.selected ? 1 : 0
                            transform: Scale {
                                origin.x: 0
                                origin.y: selectionRail.height / 2
                                xScale: 1
                                yScale: rowDelegate.selected ? 1 : 0.5
                                Behavior on yScale { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeEnter } }
                            }
                            Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                        }

                        RowLayout {
                            visible: rowDelegate.rowKind === "group"
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 12
                            spacing: 8

                            VectorIcon {
                                name: "collapse"
                                color: Theme.muted
                                Layout.preferredWidth: 13
                                Layout.preferredHeight: 13
                                rotation: rowDelegate.rowCollapsed ? 180 : 0
                                Behavior on rotation { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeStandard } }
                            }
                            Text { text: shell.groupCode(rowDelegate.rowGroupIndex); color: Theme.command; font.family: Theme.mono; font.pixelSize: Theme.sp(7); font.weight: Font.Bold }
                            Text { Layout.fillWidth: true; text: rowDelegate.rowGroupName || "未分组"; color: Theme.text; font.family: Theme.sans; font.pixelSize: Theme.sp(10); font.weight: Font.Bold; elide: Text.ElideRight }
                            Text { text: shell.twoDigits(rowDelegate.rowGroupToolCount) + " UNITS"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7) }
                        }

                        Item {
                            visible: rowDelegate.rowKind === "tool"
                            anchors.fill: parent
                            transform: Translate {
                                x: rowDelegate.selected ? 2 : rowMouse.containsMouse ? 1 : 0
                                Behavior on x { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeStandard } }
                            }

                            RowLayout {
                                anchors.fill: parent
                                spacing: 0

                            Item {
                                Layout.preferredWidth: matrixPanel.seqWidth
                                Layout.fillHeight: true
                                Text { anchors.left: parent.left; anchors.leftMargin: 9; anchors.verticalCenter: parent.verticalCenter; text: rowDelegate.sequenceText || "--"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                Layout.fillWidth: true
                                Layout.preferredWidth: matrixPanel.identityWidth
                                Layout.fillHeight: true
                                Column { anchors.left: parent.left; anchors.leftMargin: 10; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                    Text { width: parent.width; text: rowDelegate.toolName || ""; color: Theme.text; font.family: Theme.sans; font.pixelSize: Theme.sp(11); font.weight: Font.Bold; elide: Text.ElideRight }
                                    Text { width: parent.width; text: rowDelegate.toolId || ""; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); elide: Text.ElideRight }
                                }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                visible: matrixPanel.showGroup
                                Layout.preferredWidth: matrixPanel.groupWidth
                                Layout.fillHeight: true
                                Column { anchors.left: parent.left; anchors.leftMargin: 9; anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                    Text { width: parent.width; text: shell.groupCode(rowDelegate.rowGroupIndex); color: Theme.command; font.family: Theme.mono; font.pixelSize: Theme.sp(7); font.weight: Font.Bold; elide: Text.ElideRight }
                                    Text { width: parent.width; text: rowDelegate.rowGroupName || "未分组"; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(7); font.weight: Font.DemiBold; elide: Text.ElideRight }
                                }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                Layout.preferredWidth: matrixPanel.stateWidth
                                Layout.fillHeight: true
                                Row { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 7
                                    Rectangle {
                                        id: stateMark
                                        width: 7
                                        height: 7
                                        color: Theme.stateColor(rowDelegate.toolState || "stopped")
                                        Behavior on color { ColorAnimation { duration: Theme.normal } }
                                    }
                                    Text { text: rowDelegate.stateLabel || ""; color: Theme.stateColor(rowDelegate.toolState || "stopped"); font.family: Theme.sans; font.pixelSize: Theme.sp(9); font.weight: Font.Bold }
                                }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                Layout.preferredWidth: matrixPanel.pidWidth
                                Layout.fillHeight: true
                                Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: rowDelegate.pidText || "----"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(8); elide: Text.ElideRight; width: parent.width - 12 }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                visible: matrixPanel.showUptime
                                Layout.preferredWidth: matrixPanel.uptimeWidth
                                Layout.fillHeight: true
                                Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: rowDelegate.toolState === "exited" ? "EXIT " + (rowDelegate.exitCodeText || "--") : rowDelegate.toolState === "stopped" ? "STANDBY" : rowDelegate.toolState === "starting" ? "STARTING" : rowDelegate.toolState === "unready" ? "TIMEOUT" : rowDelegate.uptimeText || "--"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); elide: Text.ElideRight; width: parent.width - 12 }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                Layout.fillWidth: true
                                Layout.preferredWidth: matrixPanel.cwdWidth
                                Layout.fillHeight: true
                                Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: rowDelegate.toolCwd || ""; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); elide: Text.ElideMiddle }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                visible: matrixPanel.showAutostart
                                Layout.preferredWidth: matrixPanel.autostartWidth
                                Layout.fillHeight: true
                                Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: rowDelegate.toolAutostart ? "ENABLED" : "DISABLED"; color: rowDelegate.toolAutostart ? Theme.telemetryDark : Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); elide: Text.ElideRight; width: parent.width - 12 }
                                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
                            }
                            Item {
                                Layout.preferredWidth: matrixPanel.dragWidth
                                Layout.fillHeight: true
                                VectorIcon {
                                    anchors.centerIn: parent
                                    name: "drag"
                                    color: Theme.faint
                                    width: 15
                                    height: 15
                                    opacity: rowMouse.containsMouse || rowDelegate.dragging ? 1 : 0.58
                                    Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                                }
                            }
                            }
                        }

                        SequentialAnimation {
                            id: statePulse
                            ParallelAnimation {
                                NumberAnimation { target: stateMark; property: "opacity"; from: 0.42; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
                                NumberAnimation { target: stateMark; property: "scale"; from: 1.65; to: 1; duration: Theme.normal; easing.type: Theme.easeEnter }
                            }
                        }

                        MouseArea {
                            id: rowMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            preventStealing: true
                            onPressed: function(mouse) {
                                rowDelegate.dragging = false
                                rowDelegate.pressX = mouse.x
                                rowDelegate.pressY = mouse.y
                            }
                            onPositionChanged: function(mouse) {
                                if (!rowMouse.pressed || !shell.bridge.reorderingAllowed)
                                    return
                                if (!rowDelegate.dragging && Math.hypot(mouse.x - rowDelegate.pressX, mouse.y - rowDelegate.pressY) > 6) {
                                    rowDelegate.dragging = true
                                    shell.draggingLabel = rowDelegate.rowKind === "group" ? rowDelegate.rowGroupName : rowDelegate.toolName
                                }
                                if (!rowDelegate.dragging)
                                    return
                                var point = mapToItem(archiveList, mouse.x, mouse.y)
                                if (point.y < 38)
                                    archiveList.contentY = Math.max(0, archiveList.contentY - 10)
                                else if (point.y > archiveList.height - 38)
                                    archiveList.contentY = Math.min(Math.max(0, archiveList.contentHeight - archiveList.height), archiveList.contentY + 10)
                                shell.updateDropTarget(point.y)
                            }
                            onReleased: function(mouse) {
                                if (!rowDelegate.dragging) {
                                    if (rowDelegate.rowKind === "group")
                                        shell.bridge.toggleGroup(rowDelegate.rowGroupKey)
                                    else
                                        shell.bridge.selectTool(rowDelegate.toolId)
                                    return
                                }
                                var point = mapToItem(archiveList, mouse.x, mouse.y)
                                shell.commitDrop(rowDelegate.rowKind, rowDelegate.rowGroupKey, rowDelegate.toolId || "", point.y)
                                rowDelegate.dragging = false
                                shell.dropTargetRow = -1
                                shell.draggingLabel = ""
                            }
                            onCanceled: {
                                rowDelegate.dragging = false
                                shell.dropTargetRow = -1
                                shell.draggingLabel = ""
                            }
                        }
                    }

                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    Rectangle {
                        visible: shell.dropTargetRow >= 0 && shell.draggingLabel.length > 0
                        x: 5
                        y: shell.dropTargetY - 1
                        width: archiveList.width - 10
                        height: 2
                        color: Theme.command
                        z: 50
                    }
                }

                Column {
                    visible: shell.bridge && shell.bridge.toolModel.visibleCount === 0
                    anchors.centerIn: archiveList
                    width: archiveList.width - 48
                    spacing: 9

                    Text { width: parent.width; text: shell.bridge.toolModel.totalCount === 0 ? "NO REGISTERED UNITS" : "NO MATCHING UNITS"; color: Theme.text; font.family: Theme.mono; font.pixelSize: Theme.sp(11); font.weight: Font.Bold; horizontalAlignment: Text.AlignHCenter }
                    Text { width: parent.width; text: shell.bridge.toolModel.totalCount === 0 ? "配置索引为空" : "当前筛选无结果"; color: Theme.faint; font.family: Theme.sans; font.pixelSize: Theme.sp(10); horizontalAlignment: Text.AlignHCenter }
                    Button {
                        id: emptyAction
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 110
                        height: 34
                        text: shell.bridge.toolModel.totalCount === 0 ? "登记工具" : "清除筛选"
                        hoverEnabled: true
                        onClicked: shell.bridge.toolModel.totalCount === 0 ? shell.addRequested() : shell.bridge.clearFilters()
                        transform: Translate {
                            y: emptyAction.down ? 1 : 0
                            Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                        }
                        contentItem: Text { text: emptyAction.text; color: Theme.white; font.family: Theme.sans; font.pixelSize: Theme.sp(10); font.weight: Font.Bold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        background: Rectangle {
                            color: emptyAction.hovered ? Qt.lighter(Theme.command, 1.12) : Theme.command
                            radius: Theme.radiusSmall
                            Behavior on color { ColorAnimation { duration: Theme.fast } }
                        }
                    }
                }
            }

            Rectangle {
                id: splitter
                objectName: "archiveWorkspaceDivider"
                x: matrixPanel.width
                y: 0
                width: 8
                height: workspace.height
                color: splitterMouse.containsMouse || activeFocus ? Theme.line : Theme.fog
                border.width: Theme.lineWidth
                border.color: Theme.line
                activeFocusOnTab: true
                Accessible.name: "调整运行矩阵与工具档案宽度"

                Behavior on color { ColorAnimation { duration: Theme.fast } }

                property real pressWorkspaceX: 0
                property real pressRatio: 0.60
                property real minimumRatio: shell.minimumSplitRatio
                property real maximumRatio: shell.maximumSplitRatio
                property real currentRatio: shell.splitRatio

                VectorIcon { anchors.centerIn: parent; name: "drag"; color: Theme.muted; width: 10; height: 22 }
                Keys.onPressed: function(event) {
                    var step = event.modifiers & Qt.ShiftModifier ? 0.05 : 0.01
                    if (event.key === Qt.Key_Left)
                        shell.queueSplitRatio(shell.splitRatio - step)
                    else if (event.key === Qt.Key_Right)
                        shell.queueSplitRatio(shell.splitRatio + step)
                    else if (event.key === Qt.Key_Home)
                        shell.queueSplitRatio(shell.minimumSplitRatio)
                    else if (event.key === Qt.Key_End)
                        shell.queueSplitRatio(shell.maximumSplitRatio)
                    else
                        return
                    shell.applyPendingSplit()
                    event.accepted = true
                }

                MouseArea {
                    id: splitterMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.SplitHCursor
                    onPressed: function(mouse) {
                        splitter.forceActiveFocus()
                        splitter.pressWorkspaceX = mapToItem(workspace, mouse.x, mouse.y).x
                        splitter.pressRatio = shell.splitRatio
                    }
                    onPositionChanged: function(mouse) {
                        if (!splitterMouse.pressed)
                            return
                        var currentX = mapToItem(workspace, mouse.x, mouse.y).x
                        shell.queueSplitRatio(splitter.pressRatio + (currentX - splitter.pressWorkspaceX) / Math.max(1, workspace.usableWidth))
                    }
                    onReleased: shell.applyPendingSplit()
                    onCanceled: shell.applyPendingSplit()
                    onDoubleClicked: {
                        shell.queueSplitRatio(0.60)
                        shell.applyPendingSplit()
                    }
                }
            }

            Rectangle {
                id: dossierPanel
                objectName: "archiveDossier"
                x: splitter.x + splitter.width
                y: 0
                width: workspace.width - x
                height: workspace.height
                color: Theme.paperRaised
                clip: true
                opacity: 0.82 + shell.dossierSelectionReveal * 0.18
                transform: Translate { x: (1 - shell.dossierSelectionReveal) * Theme.shiftMedium }

                Rectangle {
                    id: dossierHead
                    width: parent.width
                    height: dossierPanel.width <= 480 ? 130 : 76
                    color: Theme.paperRaised

                    readonly property bool stackedActions: dossierPanel.width <= 480
                    readonly property bool compactActions: dossierPanel.width <= 720
                    readonly property real indexWidth: stackedActions ? 64 : 76

                    Rectangle {
                        width: dossierHead.indexWidth
                        height: parent.height
                        color: Theme.command
                        Text { anchors.centerIn: parent; text: shell.value("sequence", "--"); color: Theme.white; font.family: Theme.mono; font.pixelSize: Theme.sp(22); font.weight: Font.Bold }
                    }

                    Item {
                        x: dossierHead.indexWidth
                        width: Math.max(0, parent.width - dossierHead.indexWidth - (dossierHead.stackedActions ? 0 : dossierActionRegion.width))
                        height: 76

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.leftMargin: dossierHead.compactActions ? 14 : 18
                            anchors.rightMargin: dossierHead.compactActions ? 12 : 18
                            anchors.topMargin: 9
                            anchors.bottomMargin: 9
                            spacing: 2

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Text { text: shell.hasSelection ? shell.value("groupCode", "GRP-00") + " / " + shell.value("id", "").toUpperCase() : "NO UNIT SELECTED"; color: Theme.command; font.family: Theme.mono; font.pixelSize: Theme.sp(7); font.weight: Font.Bold; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { visible: shell.hasSelection; text: shell.value("stateLabel", ""); color: Theme.stateColor(shell.value("state", "stopped")); font.family: Theme.sans; font.pixelSize: Theme.sp(8); font.weight: Font.Bold }
                            }
                            Text { Layout.fillWidth: true; text: shell.hasSelection ? shell.value("name", "") : "工具运行档案"; color: Theme.text; font.family: Theme.condensed; font.pixelSize: Theme.sp(dossierHead.compactActions ? 20 : 23); font.weight: Font.Bold; elide: Text.ElideRight }
                            Text { Layout.fillWidth: true; text: shell.hasSelection ? shell.value("cwdShort", "") + "  ·  PID " + shell.value("pidText", "----") + "  ·  UPTIME " + shell.value("uptime", "--") + "  ·  EXIT " + shell.value("exitCode", "--") : "从运行矩阵选择一个工具"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); elide: Text.ElideMiddle }
                        }
                    }

                    Item {
                        id: dossierActionRegion
                        x: dossierHead.stackedActions ? dossierHead.indexWidth : parent.width - width
                        y: dossierHead.stackedActions ? 76 : 0
                        width: dossierHead.stackedActions
                            ? parent.width - dossierHead.indexWidth
                            : dossierActions.implicitWidth + (dossierHead.compactActions ? 24 : 36)
                        height: dossierHead.stackedActions ? 54 : 76

                        Rectangle { visible: !dossierHead.stackedActions; anchors.left: parent.left; width: 1; height: parent.height; color: Theme.line }
                        Rectangle { visible: dossierHead.stackedActions; anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }

                        Row {
                            id: dossierActions
                            anchors.right: parent.right
                            anchors.rightMargin: dossierHead.compactActions ? 12 : 18
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: dossierHead.compactActions ? 6 : 7

                            ArchiveIconButton { visible: shell.value("readyUrl", "").length > 0; iconName: "external"; kind: "neutral"; tip: "打开本地服务"; onClicked: shell.bridge.openSelectedService() }
                            ArchiveIconButton { objectName: "archiveStartAction"; iconName: "play"; label: "启动"; showLabel: !dossierHead.compactActions; symbolSize: 17; kind: "telemetry"; tip: "启动 " + shell.value("name", "工具"); enabled: shell.hasSelection && !shell.value("active", false); onClicked: shell.bridge.startSelected() }
                            ArchiveIconButton { iconName: "stop"; label: "停止"; showLabel: !dossierHead.compactActions; symbolSize: 17; kind: "command"; tip: "停止 " + shell.value("name", "工具"); enabled: shell.hasSelection && shell.value("active", false); onClicked: shell.bridge.stopSelected() }
                            ArchiveIconButton { iconName: "refresh"; label: "重启"; showLabel: !dossierHead.compactActions; symbolSize: 17; kind: "neutral"; tip: "重启 " + shell.value("name", "工具"); enabled: shell.hasSelection && shell.value("state", "stopped") !== "stopping"; onClicked: shell.bridge.restartSelected() }
                            ArchiveIconButton { iconName: "edit"; kind: "neutral"; tip: "编辑工具配置"; enabled: shell.hasSelection; onClicked: shell.editRequested() }
                        }
                    }

                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                }

                Rectangle {
                    id: dossierTabs
                    y: dossierHead.height
                    width: parent.width
                    height: 38
                    color: Theme.fog

                    Row {
                        x: dossierHead.indexWidth
                        height: parent.height

                        Repeater {
                            model: ["运行记录", "配置档案"]
                            Button {
                                id: dossierTabButton
                                required property int index
                                required property string modelData
                                width: 120
                                height: dossierTabs.height
                                text: modelData
                                hoverEnabled: true
                                onClicked: shell.dossierTab = dossierTabButton.index
                                transform: Translate {
                                    y: dossierTabButton.down ? 1 : 0
                                    Behavior on y { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                                }
                                contentItem: Text { text: dossierTabButton.text; color: shell.dossierTab === dossierTabButton.index ? Theme.text : Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(10); font.weight: Font.Bold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                background: Rectangle {
                                    color: shell.dossierTab === dossierTabButton.index ? Theme.paperRaised : dossierTabButton.hovered ? Theme.fog : "transparent"
                                    border.width: Theme.lineWidth
                                    border.color: Theme.line
                                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                                    Rectangle {
                                        id: dossierTabMarker
                                        anchors.top: parent.top
                                        width: parent.width
                                        height: 3
                                        color: Theme.command
                                        opacity: shell.dossierTab === dossierTabButton.index ? 1 : 0
                                        transform: Scale {
                                            origin.x: dossierTabMarker.width / 2
                                            origin.y: 0
                                            xScale: shell.dossierTab === dossierTabButton.index ? 1 : 0.45
                                            yScale: 1
                                            Behavior on xScale { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeEnter } }
                                        }
                                        Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                                    }
                                }
                            }
                        }
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.ink }
                }

                Item {
                    objectName: "archiveDossierStack"
                    x: 0
                    y: dossierTabs.y + dossierTabs.height
                    width: parent.width
                    height: parent.height - y
                    opacity: 0.62 + shell.dossierTabReveal * 0.38
                    transform: Translate { x: shell.dossierTabDirection * (1 - shell.dossierTabReveal) * Theme.shiftSmall }

                    StackLayout {
                        anchors.fill: parent
                        currentIndex: shell.dossierTab

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                color: Theme.paper

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 10
                                    spacing: 9

                                    Rectangle { Layout.preferredWidth: 6; Layout.preferredHeight: 6; color: shell.value("active", false) ? Theme.telemetry : Theme.faint }
                                    Text { text: "LIVE RECORD"; color: Theme.muted; font.family: Theme.mono; font.pixelSize: Theme.sp(7); font.weight: Font.Bold }
                                    Text { Layout.fillWidth: true; text: shell.hasSelection ? shell.value("logPath", "") : "NO CHANNEL"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(7); elide: Text.ElideMiddle }
                                    CheckBox {
                                        id: archiveFollowLog
                                        checked: true
                                        text: "跟随"
                                        leftPadding: 0
                                        spacing: 5
                                        indicator: Rectangle {
                                            implicitWidth: 12
                                            implicitHeight: 12
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: archiveFollowLog.checked ? Theme.telemetry : "transparent"
                                            border.width: Theme.lineWidth
                                            border.color: archiveFollowLog.checked ? Theme.telemetry : Theme.line

                                            Behavior on color { ColorAnimation { duration: Theme.fast } }
                                            Behavior on border.color { ColorAnimation { duration: Theme.fast } }

                                            VectorIcon {
                                                anchors.centerIn: parent
                                                name: "check"
                                                color: Theme.white
                                                width: 9
                                                height: 9
                                                strokeWidth: 2.2
                                                opacity: archiveFollowLog.checked ? 1 : 0
                                                scale: archiveFollowLog.checked ? 1 : 0.55

                                                Behavior on opacity { NumberAnimation { duration: Theme.fast; easing.type: Theme.easeStandard } }
                                                Behavior on scale { NumberAnimation { duration: Theme.normal; easing.type: Theme.easeEnter } }
                                            }
                                        }
                                        contentItem: Text { text: archiveFollowLog.text; color: Theme.muted; font.family: Theme.sans; font.pixelSize: Theme.sp(8); leftPadding: archiveFollowLog.indicator.width + archiveFollowLog.spacing; verticalAlignment: Text.AlignVCenter }
                                    }
                                    ArchiveIconButton { implicitWidth: 32; implicitHeight: 32; iconName: "external"; kind: "neutral"; tip: "定位完整日志"; enabled: shell.hasSelection; onClicked: shell.bridge.openSelectedLog() }
                                    ArchiveIconButton { objectName: "archiveCopyLogAction"; implicitWidth: 32; implicitHeight: 32; iconName: "copy"; kind: "neutral"; tip: "复制当前显示的运行记录"; enabled: shell.bridge && shell.bridge.logText.trim().length > 0; onClicked: shell.bridge.copyVisibleLog() }
                                    ArchiveIconButton { implicitWidth: 32; implicitHeight: 32; iconName: "clear"; kind: "neutral"; tip: "清空当前显示"; enabled: shell.hasSelection; onClicked: shell.bridge.clearVisibleLog() }
                                }
                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                            }

                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true

                                ListView {
                                    id: archiveLogText
                                    objectName: "archiveLogText"
                                    anchors.fill: parent
                                    model: shell.bridge ? shell.bridge.logModel : null
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    reuseItems: true
                                    cacheBuffer: 160

                                    onCountChanged: {
                                        if (archiveFollowLog.checked && count > 0)
                                            Qt.callLater(function() { archiveLogText.positionViewAtEnd() })
                                    }

                                    delegate: Item {
                                        id: logRow
                                        required property string logTime
                                        required property string logLevel
                                        required property string logMessage
                                        width: ListView.view ? ListView.view.width : archiveLogText.width
                                        height: Math.max(28, logMessageLabel.implicitHeight + 12)

                                        Rectangle { anchors.fill: parent; color: logRow.logLevel === "command" ? "#fff3e7" : Theme.paperRaised }
                                        Rectangle { anchors.left: parent.left; width: 5; height: parent.height; color: shell.logAccent(logRow.logLevel) }
                                        Rectangle { x: 91; width: 1; height: parent.height; color: Theme.line }
                                        Rectangle { x: 153; width: 1; height: parent.height; color: Theme.line }
                                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#e5e5de" }

                                        TextEdit {
                                            id: logTimeLabel
                                            objectName: "archiveLogTime"
                                            x: 15
                                            y: 7
                                            width: 66
                                            text: logRow.logTime || "--:--:--"
                                            readOnly: true
                                            selectByMouse: true
                                            persistentSelection: true
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.NoWrap
                                            clip: true
                                            color: Theme.faint
                                            selectionColor: Theme.command
                                            selectedTextColor: Theme.white
                                            font.family: Theme.mono
                                            font.pixelSize: Theme.sp(8)
                                        }
                                        TextEdit {
                                            id: logLevelLabel
                                            objectName: "archiveLogLevel"
                                            x: 101
                                            y: 7
                                            width: 42
                                            text: logRow.logLevel.toUpperCase()
                                            readOnly: true
                                            selectByMouse: true
                                            persistentSelection: true
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.NoWrap
                                            clip: true
                                            color: Theme.muted
                                            selectionColor: Theme.command
                                            selectedTextColor: Theme.white
                                            font.family: Theme.mono
                                            font.pixelSize: Theme.sp(7)
                                            font.weight: Font.Bold
                                        }
                                        TextEdit {
                                            id: logMessageLabel
                                            objectName: "archiveLogMessage"
                                            x: 164
                                            y: 6
                                            width: Math.max(0, parent.width - x - 10)
                                            text: logRow.logMessage
                                            readOnly: true
                                            selectByMouse: true
                                            persistentSelection: true
                                            textFormat: TextEdit.PlainText
                                            color: Theme.text
                                            selectionColor: Theme.command
                                            selectedTextColor: Theme.white
                                            font.family: Theme.mono
                                            font.pixelSize: Theme.sp(9)
                                            wrapMode: TextEdit.WrapAnywhere
                                        }
                                    }

                                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                }
                                Text { visible: shell.hasSelection && shell.bridge && shell.bridge.logModel.count === 0; anchors.centerIn: parent; text: "AWAITING OUTPUT"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.sp(10); font.weight: Font.Bold }
                            }
                        }
                    }

                    ScrollView {
                        id: manifestScroll
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                        GridLayout {
                            width: manifestScroll.availableWidth
                            columns: dossierPanel.width > 720 ? 4 : 2
                            columnSpacing: 0
                            rowSpacing: 0

                            ArchiveManifestCell { Layout.fillWidth: true; label: "Group"; value: shell.value("groupLabel", "未分组") }
                            ArchiveManifestCell { Layout.fillWidth: true; label: "Tool ID"; value: shell.value("id", "--") }
                            ArchiveManifestCell { Layout.fillWidth: true; label: "Shell"; value: shell.value("shell", "--") }
                            ArchiveManifestCell { Layout.fillWidth: true; label: "Autostart"; value: shell.value("autostart", false) ? "ENABLED" : "DISABLED" }
                            ArchiveManifestCell { Layout.fillWidth: true; label: "Stop signal"; value: shell.value("stopSignal", "--") }
                            ArchiveManifestCell { Layout.fillWidth: true; label: "Stop timeout"; value: shell.value("stopTimeout", "--") + " SECONDS" }
                            ArchiveManifestCell { Layout.columnSpan: parent.columns; Layout.fillWidth: true; label: "Working directory"; value: shell.value("cwdShort", "--") }
                            ArchiveManifestCell { Layout.columnSpan: parent.columns; Layout.fillWidth: true; label: "Command payload"; value: shell.value("cmd", "--"); multiline: true }
                            ArchiveManifestCell { Layout.columnSpan: parent.columns; Layout.fillWidth: true; label: "Environment"; value: shell.value("envText", "") || "NO VARIABLES"; multiline: true }
                        }
                    }
                    }
                }
            }
        }

        Rectangle {
            objectName: "archiveStatusLine"
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            color: Theme.ink

            Text { anchors.left: parent.left; anchors.leftMargin: 14; anchors.verticalCenter: parent.verticalCenter; text: "SELECTED / " + (shell.hasSelection ? shell.value("id", "").toUpperCase() : "NONE"); color: Theme.mutedOnDark; font.family: Theme.mono; font.pixelSize: Theme.sp(7) }
            Text { anchors.centerIn: parent; text: "APPLICATION CORE / CONNECTED"; color: Theme.telemetry; font.family: Theme.mono; font.pixelSize: Theme.sp(7) }
            Text { anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter; text: "VISIBLE " + (shell.bridge ? shell.twoDigits(shell.bridge.toolModel.visibleCount) : "00") + " / " + (shell.bridge ? shell.twoDigits(shell.bridge.toolModel.totalCount) : "00"); color: Theme.mutedOnDark; font.family: Theme.mono; font.pixelSize: Theme.sp(7) }
        }
    }
}
