from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot

from tooldeck.config import ToolConfig
from tooldeck.layout import LayoutState
from tooldeck.procs import ToolStatus
from tooldeck.util import fmt_duration, short_home


STATE_LABELS = {
    "loading": "读取中",
    "error": "状态异常",
    "running": "运行中",
    "stopping": "停止中",
    "exited": "已退出",
    "stopped": "已停止",
}


STATE_COLORS = {
    "loading": "#7b827e",
    "error": "#ec5a36",
    "running": "#16b8a6",
    "stopping": "#f0c928",
    "exited": "#ec5a36",
    "stopped": "#7b827e",
}

class ToolListModel(QAbstractListModel):
    """Flat presentation model containing group headers and tool rows.

    ``visibleCount`` and ``get`` intentionally keep their historical
    tool-only semantics for CLI/GUI callers. QML uses the row roles directly.
    """

    countsChanged = Signal()

    ToolIdRole = Qt.ItemDataRole.UserRole + 1
    NameRole = ToolIdRole + 1
    CwdRole = NameRole + 1
    CommandRole = CwdRole + 1
    StateRole = CommandRole + 1
    StateLabelRole = StateRole + 1
    StateColorRole = StateLabelRole + 1
    ActiveRole = StateColorRole + 1
    PidTextRole = ActiveRole + 1
    UptimeRole = PidTextRole + 1
    AutostartRole = UptimeRole + 1
    SequenceRole = AutostartRole + 1
    GroupRole = SequenceRole + 1
    RowTypeRole = GroupRole + 1
    GroupNameRole = RowTypeRole + 1
    GroupKeyRole = GroupNameRole + 1
    CollapsedRole = GroupKeyRole + 1
    DragHandleRole = CollapsedRole + 1
    GroupIndexRole = DragHandleRole + 1
    ToolIndexRole = GroupIndexRole + 1
    GroupToolCountRole = ToolIndexRole + 1

    _ROLES = {
        ToolIdRole: b"toolId",
        NameRole: b"toolName",
        CwdRole: b"toolCwd",
        CommandRole: b"toolCommand",
        StateRole: b"toolState",
        StateLabelRole: b"stateLabel",
        StateColorRole: b"stateColor",
        ActiveRole: b"toolActive",
        PidTextRole: b"pidText",
        UptimeRole: b"uptimeText",
        AutostartRole: b"toolAutostart",
        SequenceRole: b"sequenceText",
        GroupRole: b"toolGroup",
        RowTypeRole: b"rowType",
        GroupNameRole: b"groupName",
        GroupKeyRole: b"groupKey",
        CollapsedRole: b"collapsed",
        DragHandleRole: b"dragHandle",
        GroupIndexRole: b"groupIndex",
        ToolIndexRole: b"toolIndex",
        GroupToolCountRole: b"groupToolCount",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tools: dict[str, ToolConfig] = {}
        self._statuses: dict[str, ToolStatus] = {}
        self._layout = LayoutState()
        self._visible_ids: list[str] = []
        self._rows: list[tuple[str, str]] = []
        self._filter_text = ""
        self._filter_state = "all"
        self._published: list[dict[int, object]] = []

    def roleNames(self) -> dict[int, bytes]:
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def _row_tool_id(self, row: int) -> str | None:
        if 0 <= row < len(self._rows) and self._rows[row][0] == "tool":
            return self._rows[row][1]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row_type, value = self._rows[index.row()]
        if row_type == "group":
            if role == self.RowTypeRole:
                return "group"
            if role in {self.GroupNameRole, Qt.ItemDataRole.DisplayRole}:
                return value or "未分组"
            if role == self.GroupKeyRole:
                return value
            if role == self.CollapsedRole:
                return value in self._layout.collapsed_groups and not self._filter_active
            if role == self.DragHandleRole:
                return True
            if role == self.GroupIndexRole:
                return self._layout.group_order.index(value)
            if role == self.ToolIndexRole:
                return -1
            if role == self.GroupToolCountRole:
                return len(self._layout.tool_order.get(value, []))
            return None

        tool_id = value
        tool = self._tools[tool_id]
        status = self._statuses.get(tool_id, ToolStatus(tool_id, "stopped"))
        if role == self.RowTypeRole:
            return "tool"
        if role == self.ToolIdRole:
            return tool.id
        if role in {self.NameRole, Qt.ItemDataRole.DisplayRole}:
            return tool.name
        if role == self.CwdRole:
            return short_home(tool.cwd)
        if role == self.CommandRole:
            return tool.cmd
        if role == self.StateRole:
            return status.state
        if role == self.StateLabelRole:
            return STATE_LABELS.get(status.state, status.state)
        if role == self.StateColorRole:
            return STATE_COLORS.get(status.state, STATE_COLORS["stopped"])
        if role == self.ActiveRole:
            return status.active
        if role == self.PidTextRole:
            return str(status.pid) if status.pid else "----"
        if role == self.UptimeRole:
            return fmt_duration(status.uptime)
        if role == self.AutostartRole:
            return tool.autostart
        if role == self.SequenceRole:
            return f"{self._ordered_ids().index(tool_id) + 1:02d}"
        if role in {self.GroupRole, self.GroupNameRole}:
            return tool.group or "未分组"
        if role == self.GroupKeyRole:
            return tool.group or ""
        if role == self.DragHandleRole:
            return True
        if role == self.GroupIndexRole:
            return self._layout.group_order.index(tool.group or "")
        if role == self.ToolIndexRole:
            return self._layout.tool_order.get(tool.group or "", []).index(tool_id)
        if role == self.GroupToolCountRole:
            return len(self._layout.tool_order.get(tool.group or "", []))
        return None

    @property
    def _filter_active(self) -> bool:
        return bool(self._filter_text.strip()) or self._filter_state != "all"

    def _ordered_ids(self) -> list[str]:
        result: list[str] = []
        for group in self._layout.group_order:
            result.extend(tool_id for tool_id in self._layout.tool_order.get(group, []) if tool_id in self._tools)
        result.extend(tool_id for tool_id in self._tools if tool_id not in result)
        return result

    def _matches(self, tool_id: str) -> bool:
        tool = self._tools[tool_id]
        status = self._statuses.get(tool_id, ToolStatus(tool_id, "stopped"))
        if self._filter_state == "running" and not status.active:
            return False
        if self._filter_state == "stopped" and status.active:
            return False
        query = self._filter_text.casefold().strip()
        if not query:
            return True
        return query in "\n".join((tool.name, tool.id, tool.cwd, tool.group)).casefold()

    def _rebuild(self) -> bool:
        visible: list[str] = []
        rows: list[tuple[str, str]] = []
        by_group: dict[str, list[str]] = {group: [] for group in self._layout.group_order}
        for tool_id in self._ordered_ids():
            group = self._tools[tool_id].group or ""
            by_group.setdefault(group, []).append(tool_id)
        for group in self._layout.group_order:
            group_tools = [tool_id for tool_id in by_group.get(group, []) if self._matches(tool_id)]
            if self._filter_active and not group_tools:
                continue
            rows.append(("group", group))
            if not (group in self._layout.collapsed_groups and not self._filter_active):
                rows.extend(("tool", tool_id) for tool_id in group_tools)
            visible.extend(group_tools)
        if rows == self._rows and visible == self._visible_ids:
            return False
        self.beginResetModel()
        self._rows = rows
        self._visible_ids = visible
        self.endResetModel()
        return True

    def set_layout(self, layout: LayoutState) -> None:
        previous = (self.groupCount, self.visibleCount)
        self._layout = layout
        self._rebuild()
        if previous != (self.groupCount, self.visibleCount):
            self.countsChanged.emit()

    def set_tools(self, tools: dict[str, ToolConfig], statuses: dict[str, ToolStatus]) -> None:
        previous_counts = (self.totalCount, self.visibleCount, self.runningCount)
        self._tools = dict(tools)
        self._statuses = dict(statuses)
        rebuilt = self._rebuild()
        current = [{role: self.data(self.index(row, 0), role) for role in self._ROLES} for row in range(len(self._rows))]
        if not rebuilt and len(current) == len(self._published):
            for row, values in enumerate(current):
                changed = [role for role, value in values.items() if self._published[row].get(role) != value]
                if changed:
                    self.dataChanged.emit(self.index(row, 0), self.index(row, 0), changed)
        self._published = current
        current_counts = (self.totalCount, self.visibleCount, self.runningCount)
        if current_counts != previous_counts:
            self.countsChanged.emit()


    def set_filter(self, text: str, state: str) -> None:
        normalized_state = state if state in {"all", "running", "stopped"} else "all"
        if text == self._filter_text and normalized_state == self._filter_state:
            return
        self._filter_text = text
        self._filter_state = normalized_state
        previous_visible_count = self.visibleCount
        if self._rebuild() and self.visibleCount != previous_visible_count:
            self.countsChanged.emit()

    @Property(int, notify=countsChanged)
    def totalCount(self) -> int:
        return len(self._tools)

    @Property(int, notify=countsChanged)
    def visibleCount(self) -> int:
        return len(self._visible_ids)

    @Property(int, notify=countsChanged)
    def groupCount(self) -> int:
        return sum(1 for row_type, _ in self._rows if row_type == "group")

    @Property(int, notify=countsChanged)
    def runningCount(self) -> int:
        return sum(self._statuses.get(tool_id, ToolStatus(tool_id, "stopped")).active for tool_id in self._tools)

    @Property(int, notify=countsChanged)
    def stoppedCount(self) -> int:
        return self.totalCount - self.runningCount

    @property
    def visible_ids(self) -> tuple[str, ...]:
        return tuple(self._visible_ids)

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._rows)

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, Any]:
        """Return the row-th *tool* for compatibility with the 0.1 API."""
        if not 0 <= row < len(self._visible_ids):
            return {}
        tool_row = self._rows_for_tool(self._visible_ids[row])
        return self._map_for_row(tool_row)

    @Slot(int, result="QVariantMap")
    def getRow(self, row: int) -> dict[str, Any]:
        if not 0 <= row < len(self._rows):
            return {}
        return self._map_for_row(row)

    def _rows_for_tool(self, tool_id: str) -> int:
        return next((row for row, entry in enumerate(self._rows) if entry == ("tool", tool_id)), -1)

    def _map_for_row(self, row: int) -> dict[str, Any]:
        index = self.index(row, 0)
        return {name.decode(): self.data(index, role) for role, name in self._ROLES.items()}
