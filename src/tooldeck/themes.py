"""Versioned, frontend-neutral theme pack discovery and validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .util import valid_id

THEME_SCHEMA_VERSION = 1
DEFAULT_THEME_ID = "lattice-day"

COLOR_TOKENS = frozenset(
    {
        "ink",
        "inkRaised",
        "paper",
        "paperRaised",
        "fog",
        "line",
        "lineDark",
        "text",
        "muted",
        "faint",
        "mutedOnDark",
        "faintOnDark",
        "white",
        "command",
        "commandDark",
        "telemetry",
        "telemetryDark",
        "warning",
        "danger",
        "consoleText",
        "scrim",
        "scrimStrong",
        "startupGrid",
        "startupGridDim",
        "startupPanel",
        "startupCanvas",
        "startupCanvasFill",
    }
)
FONT_TOKENS = frozenset({"sans", "condensed", "mono"})
METRIC_TOKENS = frozenset({"radiusSmall", "radiusTiny", "lineWidth"})
MOTION_TOKENS = frozenset({"fast", "normal", "slow"})
REQUIRED_TOKENS = COLOR_TOKENS | FONT_TOKENS | METRIC_TOKENS | MOTION_TOKENS
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


class ThemeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ThemeIssue:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class ThemeDefinition:
    id: str
    name: str
    appearance: str
    shell: str
    tokens: dict[str, Any]
    source: Path
    extends: str | None = None

    def qml_tokens(self) -> dict[str, Any]:
        return dict(self.tokens)

    def summary(self, built_in_dir: Path) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "appearance": self.appearance,
            "shell": self.shell,
            "source": "built-in" if self.source.parent == built_in_dir else "user",
        }


@dataclass(frozen=True, slots=True)
class ThemeCatalog:
    themes: dict[str, ThemeDefinition]
    issues: tuple[ThemeIssue, ...]

    @property
    def default_id(self) -> str:
        if DEFAULT_THEME_ID in self.themes:
            return DEFAULT_THEME_ID
        return next(iter(self.themes), "")


@dataclass(frozen=True, slots=True)
class _RawTheme:
    id: str
    name: str
    appearance: str | None
    shell: str | None
    tokens: dict[str, Any]
    source: Path
    extends: str | None


class ThemeRegistry:
    def __init__(
        self,
        *,
        built_in_dir: Path | None = None,
        custom_dir: Path | None = None,
    ) -> None:
        self.built_in_dir = (built_in_dir or Path(__file__).with_name("theme_packs")).resolve()
        self.custom_dir = (custom_dir or paths.themes_dir()).expanduser().resolve()
        self._catalog = ThemeCatalog({}, ())
        self.reload()

    @property
    def catalog(self) -> ThemeCatalog:
        return self._catalog

    def get(self, theme_id: str) -> ThemeDefinition:
        try:
            return self._catalog.themes[theme_id]
        except KeyError as exc:
            raise ThemeError(f"主题不存在：{theme_id}") from exc

    def reload(self) -> ThemeCatalog:
        records: dict[str, _RawTheme] = {}
        issues: list[ThemeIssue] = []
        for directory in (self.built_in_dir, self.custom_dir):
            if not directory.is_dir():
                continue
            for source in sorted(directory.glob("*.json")):
                try:
                    raw = _load_raw_theme(source)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ThemeError) as exc:
                    issues.append(ThemeIssue(source, str(exc)))
                    continue
                if raw.id in records:
                    issues.append(ThemeIssue(source, f"主题 ID 重复：{raw.id}"))
                    continue
                records[raw.id] = raw

        resolved: dict[str, ThemeDefinition] = {}
        resolving: set[str] = set()

        def resolve(theme_id: str) -> ThemeDefinition:
            if theme_id in resolved:
                return resolved[theme_id]
            try:
                raw = records[theme_id]
            except KeyError as exc:
                raise ThemeError(f"继承的主题不存在：{theme_id}") from exc
            if theme_id in resolving:
                raise ThemeError(f"主题继承形成循环：{theme_id}")
            resolving.add(theme_id)
            try:
                inherited: dict[str, Any] = {}
                appearance = raw.appearance
                shell = raw.shell
                if raw.extends:
                    parent = resolve(raw.extends)
                    inherited.update(parent.tokens)
                    appearance = appearance or parent.appearance
                    shell = shell or parent.shell
                inherited.update(raw.tokens)
                _validate_complete_tokens(inherited)
                if appearance not in {"light", "dark"}:
                    raise ThemeError("appearance 必须是 light 或 dark")
                shell = shell or "operations"
                if shell not in {"operations", "archive"}:
                    raise ThemeError("shell 必须是 operations 或 archive")
                theme = ThemeDefinition(
                    raw.id,
                    raw.name,
                    appearance,
                    shell,
                    inherited,
                    raw.source,
                    raw.extends,
                )
                resolved[theme_id] = theme
                return theme
            finally:
                resolving.discard(theme_id)

        for theme_id, raw in records.items():
            try:
                resolve(theme_id)
            except ThemeError as exc:
                issues.append(ThemeIssue(raw.source, str(exc)))

        candidate = ThemeCatalog(resolved, tuple(issues))
        if not candidate.themes:
            details = "; ".join(issue.message for issue in issues) or "未找到主题包"
            raise ThemeError(f"没有可用主题：{details}")
        self._catalog = candidate
        return self._catalog

    def summaries(self) -> list[dict[str, Any]]:
        return [theme.summary(self.built_in_dir) for theme in self._catalog.themes.values()]

    def ensure_custom_dir(self) -> Path:
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        return self.custom_dir


def _load_raw_theme(source: Path) -> _RawTheme:
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ThemeError("主题文件顶层必须是对象")
    if raw.get("schemaVersion") != THEME_SCHEMA_VERSION:
        raise ThemeError(f"主题 schemaVersion 必须是 {THEME_SCHEMA_VERSION}")
    theme_id = str(raw.get("id", "")).strip()
    if not valid_id(theme_id):
        raise ThemeError(f"无效的主题 ID：{theme_id or '<empty>'}")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ThemeError("主题名称不能为空")
    extends_value = raw.get("extends")
    extends = str(extends_value).strip() if extends_value is not None else None
    if extends == "":
        extends = None
    appearance_value = raw.get("appearance")
    appearance = str(appearance_value).strip() if appearance_value is not None else None
    shell_value = raw.get("shell")
    shell = str(shell_value).strip() if shell_value is not None else None
    if shell == "":
        shell = None
    tokens_value = raw.get("tokens", {})
    if not isinstance(tokens_value, Mapping):
        raise ThemeError("tokens 必须是对象")
    tokens = dict(tokens_value)
    for key, value in tokens.items():
        _validate_token(key, value)
    if not extends:
        _validate_complete_tokens(tokens)
    return _RawTheme(theme_id, name, appearance, shell, tokens, source.resolve(), extends)


def _validate_complete_tokens(tokens: Mapping[str, Any]) -> None:
    missing = sorted(REQUIRED_TOKENS - tokens.keys())
    if missing:
        raise ThemeError(f"缺少主题令牌：{', '.join(missing)}")
    for key in REQUIRED_TOKENS:
        _validate_token(key, tokens[key])


def _validate_token(key: str, value: Any) -> None:
    if key in COLOR_TOKENS:
        if not isinstance(value, str) or not _COLOR_PATTERN.fullmatch(value):
            raise ThemeError(f"颜色令牌 {key} 必须是 6 位或 8 位十六进制 Qt 颜色")
        return
    if key in FONT_TOKENS:
        if not isinstance(value, str) or not value.strip():
            raise ThemeError(f"字体令牌 {key} 不能为空")
        return
    if key in METRIC_TOKENS | MOTION_TOKENS:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ThemeError(f"数值令牌 {key} 必须是非负数")
        if key in MOTION_TOKENS and value > 5000:
            raise ThemeError(f"动画令牌 {key} 不能超过 5000ms")
