from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot

from tooldeck.config import ToolConfig
from tooldeck.groups import display_group_name
from tooldeck.layout import LayoutState
from tooldeck.procs import ToolStatus
from tooldeck.util import fmt_duration, short_home


STATE_LABELS = {
    "starting": "正在启动",
    "running": "运行中",
    "unready": "启动超时",
    "stopping": "停止中",
    "exited": "已退出",
    "stopped": "已停止",
}

STATE_COLORS = {
    "starting": "#f0c928",
    "running": "#16b8a6",
    "unready": "#ec5a36",
    "stopping": "#f0c928",
    "exited": "#ec5a36",
    "stopped": "#7b827e",
}

_STOPPED_STATUS = ToolStatus("", "stopped")


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
    ExitCodeRole = UptimeRole + 1
    AutostartRole = ExitCodeRole + 1
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
        ExitCodeRole: b"exitCodeText",
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
        self._running_count = 0
        self._idle_count = 0
        self._exited_count = 0

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
                return display_group_name(value)
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
        status = self._statuses.get(tool_id, _STOPPED_STATUS)
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
        if role == self.ExitCodeRole:
            return str(status.exit_code) if status.exit_code is not None else "--"
        if role == self.AutostartRole:
            return tool.autostart
        if role == self.SequenceRole:
            return self.sequence_text(tool_id)
        if role in {self.GroupRole, self.GroupNameRole}:
            return display_group_name(tool.group)
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
        seen: set[str] = set()
        for group in self._layout.group_order:
            for tool_id in self._layout.tool_order.get(group, []):
                if tool_id in self._tools and tool_id not in seen:
                    result.append(tool_id)
                    seen.add(tool_id)
        result.extend(tool_id for tool_id in self._tools if tool_id not in seen)
        return result

    def _matches(self, tool_id: str) -> bool:
        tool = self._tools[tool_id]
        status = self._statuses.get(tool_id, _STOPPED_STATUS)
        if self._filter_state == "running" and not status.active:
            return False
        if self._filter_state == "stopped" and status.state != "stopped":
            return False
        if self._filter_state == "exited" and status.state != "exited":
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
        self._layout = layout
        self._rebuild()

    def set_tools(self, tools: dict[str, ToolConfig], statuses: dict[str, ToolStatus]) -> set[str]:
        previous_tools = self._tools
        previous_statuses = self._statuses
        previous_counts = (
            self.totalCount,
            self.visibleCount,
            self.runningCount,
            self.idleCount,
            self.exitedCount,
        )
        tool_keys_changed = previous_tools.keys() != tools.keys()
        tools_values_changed = previous_tools != tools
        group_changed = tool_keys_changed or (
            tools_values_changed
            and any(
                previous_tools[tool_id].group != tool.group
                for tool_id, tool in tools.items()
                if tool_id in previous_tools
            )
        )
        search_fields_changed = bool(self._filter_text.strip()) and tools_values_changed and any(
            previous_tools.get(tool_id) is None
            or (
                previous_tools[tool_id].name,
                previous_tools[tool_id].cwd,
                previous_tools[tool_id].group,
            )
            != (tool.name, tool.cwd, tool.group)
            for tool_id, tool in tools.items()
        )
        status_values_changed = previous_statuses != statuses
        status_filter_changed = self._filter_state != "all" and status_values_changed
        self._tools = dict(tools)
        self._statuses = dict(statuses)
        states = [self._statuses.get(tool_id, _STOPPED_STATUS) for tool_id in self._tools]
        self._running_count = sum(status.active for status in states)
        self._idle_count = sum(status.state == "stopped" for status in states)
        self._exited_count = sum(status.state == "exited" for status in states)
        rebuilt = self._rebuild() if group_changed or search_fields_changed or status_filter_changed else False
        changed_ids: set[str] = set()
        if rebuilt:
            changed_ids.update(self._tools)
        elif self._rows and (tools_values_changed or status_values_changed or self._running_count):
            changed_rows: list[tuple[int, tuple[int, ...]]] = []
            uptime_rows: list[int] = []
            tool_roles = (
                self.NameRole,
                self.CwdRole,
                self.CommandRole,
                self.AutostartRole,
                self.GroupRole,
                self.GroupNameRole,
                self.GroupKeyRole,
            )
            for row, (row_type, tool_id) in enumerate(self._rows):
                if row_type != "tool":
                    continue
                roles: set[int] = set()
                old_tool = previous_tools.get(tool_id)
                new_tool = self._tools[tool_id]
                if old_tool != new_tool:
                    changed_ids.add(tool_id)
                    roles.update(tool_roles)

                old_status = previous_statuses.get(tool_id, _STOPPED_STATUS)
                new_status = self._statuses.get(tool_id, _STOPPED_STATUS)
                if old_status != new_status:
                    changed_ids.add(tool_id)
                    if old_status.state != new_status.state:
                        roles.update(
                            {
                                self.StateRole,
                                self.StateLabelRole,
                                self.StateColorRole,
                                self.ActiveRole,
                                self.UptimeRole,
                            }
                        )
                    if old_status.pid != new_status.pid:
                        roles.add(self.PidTextRole)
                    if (
                        old_status.started_at != new_status.started_at
                        or old_status.exited_at != new_status.exited_at
                    ):
                        roles.add(self.UptimeRole)
                    if old_status.exit_code != new_status.exit_code:
                        roles.add(self.ExitCodeRole)
                if new_status.active:
                    changed_ids.add(tool_id)
                    uptime_rows.append(row)
                    roles.discard(self.UptimeRole)
                if roles:
                    changed_rows.append((row, tuple(sorted(roles))))

            for row, roles in changed_rows:
                self.dataChanged.emit(self.index(row, 0), self.index(row, 0), list(roles))
            if uptime_rows:
                self.dataChanged.emit(
                    self.index(min(uptime_rows), 0),
                    self.index(max(uptime_rows), 0),
                    [self.UptimeRole],
                )
        current_counts = (
            self.totalCount,
            self.visibleCount,
            self.runningCount,
            self.idleCount,
            self.exitedCount,
        )
        if current_counts != previous_counts:
            self.countsChanged.emit()
        return changed_ids

    def set_filter(self, text: str, state: str) -> None:
        normalized_state = state if state in {"all", "running", "stopped", "exited"} else "all"
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
        return self._running_count

    @Property(int, notify=countsChanged)
    def stoppedCount(self) -> int:
        return self.totalCount - self.runningCount

    @Property(int, notify=countsChanged)
    def idleCount(self) -> int:
        return self._idle_count

    @Property(int, notify=countsChanged)
    def exitedCount(self) -> int:
        return self._exited_count

    @property
    def visible_ids(self) -> tuple[str, ...]:
        return tuple(self._visible_ids)

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._rows)

    def sequence_text(self, tool_id: str) -> str:
        ordered = self._ordered_ids()
        return f"{ordered.index(tool_id) + 1:02d}" if tool_id in ordered else "--"

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
