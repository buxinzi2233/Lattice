"""Lazy frontend discovery for built-in and third-party adapters."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from importlib import metadata
from typing import Callable, Protocol

from .application import ToolDeckApplication

ENTRY_POINT_GROUP = "tooldeck.frontends"


class FrontendError(RuntimeError):
    pass


class FrontendRunner(Protocol):
    def __call__(self, application: ToolDeckApplication) -> int: ...


@dataclass(frozen=True, slots=True)
class FrontendSpec:
    id: str
    name: str
    source: str
    loader: Callable[[], object]


def _load_object(reference: str) -> object:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise FrontendError(f"无效的前端入口：{reference}")
    return getattr(importlib.import_module(module_name), attribute)


def _builtin_qml_loader() -> object:
    return _load_object("tooldeck.gui.app:run_frontend")


def discover_frontends(
    *,
    entry_points_provider: Callable[[], object] | None = None,
) -> tuple[FrontendSpec, ...]:
    specs: dict[str, FrontendSpec] = {
        "qml": FrontendSpec("qml", "Qt Quick / QML", "built-in", _builtin_qml_loader)
    }
    provider = entry_points_provider or metadata.entry_points
    discovered = provider()
    selected = discovered.select(group=ENTRY_POINT_GROUP) if hasattr(discovered, "select") else discovered.get(ENTRY_POINT_GROUP, ())
    for entry_point in selected:
        frontend_id = str(entry_point.name).strip()
        if not frontend_id or frontend_id in specs:
            continue
        specs[frontend_id] = FrontendSpec(
            frontend_id,
            frontend_id,
            f"entry-point:{entry_point.value}",
            entry_point.load,
        )
    return tuple(specs.values())


def load_frontend(
    frontend_id: str,
    *,
    entry_points_provider: Callable[[], object] | None = None,
) -> FrontendRunner:
    specs = {spec.id: spec for spec in discover_frontends(entry_points_provider=entry_points_provider)}
    try:
        loaded = specs[frontend_id].loader()
    except KeyError as exc:
        available = ", ".join(specs)
        raise FrontendError(f"未知前端 {frontend_id}；可用前端：{available}") from exc
    except Exception as exc:
        raise FrontendError(f"无法加载前端 {frontend_id}：{exc}") from exc
    runner = loaded if callable(loaded) else getattr(loaded, "run", None)
    if not callable(runner):
        raise FrontendError(f"前端 {frontend_id} 未提供可调用的 run 接口")
    return runner


def run_frontend(
    frontend_id: str,
    *,
    application: ToolDeckApplication | None = None,
    entry_points_provider: Callable[[], object] | None = None,
) -> int:
    runner = load_frontend(frontend_id, entry_points_provider=entry_points_provider)
    result = runner(application or ToolDeckApplication())
    return int(result) if result is not None else 0
