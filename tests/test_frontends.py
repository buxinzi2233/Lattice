from __future__ import annotations

import pytest

from tooldeck.application import ToolDeckApplication
from tooldeck.frontends import FrontendError, discover_frontends, run_frontend


class FakeEntryPoint:
    name = "text"
    value = "example.frontend:run"

    def __init__(self, runner):
        self._runner = runner

    def load(self):
        return self._runner


class FakeEntryPoints(list):
    def select(self, *, group: str):
        return self if group == "tooldeck.frontends" else []


def test_frontend_registry_keeps_qt_lazy_and_runs_plugins():
    received: list[ToolDeckApplication] = []

    def runner(application: ToolDeckApplication) -> int:
        received.append(application)
        return 17

    provider = lambda: FakeEntryPoints([FakeEntryPoint(runner)])
    specs = discover_frontends(entry_points_provider=provider)
    assert [(spec.id, spec.source) for spec in specs] == [
        ("qml", "built-in"),
        ("text", "entry-point:example.frontend:run"),
    ]

    application = ToolDeckApplication()
    assert run_frontend("text", application=application, entry_points_provider=provider) == 17
    assert received == [application]


def test_unknown_frontend_reports_available_adapters():
    with pytest.raises(FrontendError, match="未知前端 missing.*qml"):
        run_frontend("missing", entry_points_provider=lambda: FakeEntryPoints())


def test_frontend_without_exit_code_defaults_to_zero():
    def runner(application: ToolDeckApplication) -> None:
        return None

    provider = lambda: FakeEntryPoints([FakeEntryPoint(runner)])
    application = ToolDeckApplication()
    assert run_frontend("text", application=application, entry_points_provider=provider) == 0
