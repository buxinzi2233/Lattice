"""Canonical group keys and presentation labels.

Group keys are persisted exactly as raw strings. Display labels are derived at
the presentation boundary so the empty key never aliases a user-created group.
"""

from __future__ import annotations

from typing import NewType

GroupKey = NewType("GroupKey", str)

UNGROUPED_KEY = GroupKey("")
UNGROUPED_LABEL = "未分组"


def normalize_group_key(value: str) -> GroupKey:
    return GroupKey(value.strip())


def display_group_name(value: str) -> str:
    key = normalize_group_key(value)
    if key == UNGROUPED_KEY:
        return UNGROUPED_LABEL
    if key == UNGROUPED_LABEL:
        return f"{UNGROUPED_LABEL}（自定义分组）"
    return str(key)
