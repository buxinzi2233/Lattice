from __future__ import annotations

from tooldeck.gui.preferences import application_settings

from datetime import date

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QSettings
from PySide6.QtGui import QImage

from tooldeck import paths
from tooldeck.startup import (
    StartupPreferences,
    cached_image_url,
    clear_cache,
    download_image,
    image_cache_path,
    is_allowed_url,
    validate_image_payload,
)


def settings() -> QSettings:
    return application_settings()


def test_startup_daily_modes_and_shuffle_bag(qapp):
    prefs = StartupPreferences(settings())
    today = date(2026, 8, 2)
    assert prefs.should_show("daily", today=today) is True
    prefs.mark_shown(today=today)
    assert prefs.should_show("daily", today=today) is False
    assert prefs.should_show("always", today=today) is True
    assert prefs.should_show("off", today=today) is False
    first = prefs.take_entry([{"id": "a"}, {"id": "b"}])
    second = prefs.take_entry([{"id": "a"}, {"id": "b"}])
    assert first["id"] != second["id"]


def test_startup_url_and_payload_guards(tmp_path):
    assert is_allowed_url("https://www.arknights.global/example.png") is True
    assert is_allowed_url("http://www.arknights.global/example.png") is False
    assert is_allowed_url("https://example.com/example.png") is False
    png = bytes.fromhex("89504e470d0a1a0a") + bytes(8) + (10).to_bytes(4, "big") + (20).to_bytes(4, "big") + b"data"
    assert validate_image_payload(png, "image/png") == ("image/png", 10, 20)
    with pytest.raises(ValueError, match="MIME"):
        validate_image_payload(png, "image/jpeg")
    with pytest.raises(ValueError, match="文件头"):
        validate_image_payload(b"not an image", "image/png")


def test_clear_startup_cache_removes_files_and_dirs():
    cache = paths.startup_cache_dir()
    cache.mkdir(parents=True)
    (cache / "a.png").write_bytes(b"x")
    (cache / "nested").mkdir()
    (cache / "nested" / "b.png").write_bytes(b"x")
    assert clear_cache(cache) == 2
    assert list(cache.iterdir()) == []


def test_download_image_decodes_and_scales_before_caching(monkeypatch, tmp_path, qapp):
    source = QImage(2000, 1000, QImage.Format.Format_RGBA8888)
    source.fill(0xFF16B8A6)
    buffer = QBuffer()
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert source.save(buffer, "PNG")
    payload = bytes(buffer.data())

    class Response:
        headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return payload

    monkeypatch.setattr("tooldeck.startup.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    entry = {"id": "silence", "image_url": "https://www.arknights.global/silence.png"}
    destination = image_cache_path(tmp_path, entry)
    assert download_image(entry["image_url"], destination) == destination
    cached = QImage(str(destination))
    assert cached.width() == 1600
    assert cached.height() == 800
    assert cached_image_url(tmp_path, entry).startswith("file://")
