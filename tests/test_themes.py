from __future__ import annotations

import json

from tooldeck.themes import ThemeRegistry


def test_builtin_theme_packs_are_complete():
    registry = ThemeRegistry()
    assert list(registry.catalog.themes) == ["lattice-archive", "lattice-day", "lattice-night"]
    assert registry.get("lattice-archive").shell == "archive"
    assert registry.get("lattice-day").appearance == "light"
    assert registry.get("lattice-day").shell == "operations"
    assert registry.get("lattice-night").appearance == "dark"
    assert registry.get("lattice-night").tokens["command"] == "#ff704d"


def test_custom_theme_can_inherit_and_override_tokens(tmp_path):
    custom_dir = tmp_path / "themes.d"
    custom_dir.mkdir()
    (custom_dir / "operator.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "operator-green",
                "name": "Operator Green",
                "extends": "lattice-day",
                "tokens": {"command": "#2f7f53"},
            }
        ),
        encoding="utf-8",
    )

    registry = ThemeRegistry(custom_dir=custom_dir)
    theme = registry.get("operator-green")
    assert theme.appearance == "light"
    assert theme.shell == "operations"
    assert theme.extends == "lattice-day"
    assert theme.tokens["command"] == "#2f7f53"
    assert theme.tokens["paper"] == registry.get("lattice-day").tokens["paper"]


def test_invalid_custom_theme_is_isolated_from_valid_packs(tmp_path):
    custom_dir = tmp_path / "themes.d"
    custom_dir.mkdir()
    (custom_dir / "broken.json").write_text("{not json", encoding="utf-8")

    registry = ThemeRegistry(custom_dir=custom_dir)
    assert registry.catalog.default_id == "lattice-day"
    assert list(registry.catalog.themes) == ["lattice-archive", "lattice-day", "lattice-night"]
    assert len(registry.catalog.issues) == 1
    assert registry.catalog.issues[0].path.name == "broken.json"


def test_custom_theme_inherits_registered_shell_and_rejects_unknown_shell(tmp_path):
    custom_dir = tmp_path / "themes.d"
    custom_dir.mkdir()
    (custom_dir / "archive-green.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "archive-green",
                "name": "Archive Green",
                "extends": "lattice-archive",
                "tokens": {"command": "#2f7f53"},
            }
        ),
        encoding="utf-8",
    )
    (custom_dir / "unsafe-shell.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "unsafe-shell",
                "name": "Unsafe Shell",
                "extends": "lattice-day",
                "shell": "external-qml",
                "tokens": {},
            }
        ),
        encoding="utf-8",
    )

    registry = ThemeRegistry(custom_dir=custom_dir)
    assert registry.get("archive-green").shell == "archive"
    assert "unsafe-shell" not in registry.catalog.themes
    assert any(issue.path.name == "unsafe-shell.json" for issue in registry.catalog.issues)
