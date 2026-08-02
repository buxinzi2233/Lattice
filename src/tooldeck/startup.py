"""Safe, opt-in startup content for Lattice."""

from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage

ALLOWED_HOSTS = {
    "www.arknights.global",
    "arknights.global",
    "ak.hypergryph.com",
    "webusstatic.yo-star.com",
}
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_CACHED_IMAGE_DIMENSION = 1600

MANIFEST: tuple[dict[str, Any], ...] = (
    {
        "id": "silence",
        "character": "Silence",
        "faction": "莱茵生命",
        "quote": "本地记录已同步。请确认实验环境。",
        "quote_zh": "本地记录已同步。请确认实验环境。",
        "quote_en": "Local records synchronized. Confirm the lab environment.",
        "source_url": "https://www.arknights.global/",
        "official_page": "https://www.arknights.global/",
        "image_url": "",
        "image_sha256": "",
        "copyright": "(c) Hypergryph / Yostar",
        "text_type": "lattice_original_boot_line",
        "verified": True,
    },
    {
        "id": "saria",
        "character": "Saria",
        "faction": "莱茵生命",
        "quote": "安全协议接入，进程树处于可观测状态。",
        "quote_zh": "安全协议接入，进程树处于可观测状态。",
        "quote_en": "Safety protocol linked. Process trees are observable.",
        "source_url": "https://www.arknights.global/",
        "official_page": "https://www.arknights.global/",
        "image_url": "",
        "image_sha256": "",
        "copyright": "(c) Hypergryph / Yostar",
        "text_type": "lattice_original_boot_line",
        "verified": True,
    },
    {
        "id": "ifrit",
        "character": "Ifrit",
        "faction": "莱茵生命",
        "quote": "能源读数稳定，启动序列继续。",
        "quote_zh": "能源读数稳定，启动序列继续。",
        "quote_en": "Power readings stable. Bootstrap sequence continues.",
        "source_url": "https://www.arknights.global/",
        "official_page": "https://www.arknights.global/",
        "image_url": "",
        "image_sha256": "",
        "copyright": "(c) Hypergryph / Yostar",
        "text_type": "lattice_original_boot_line",
        "verified": True,
    },
)


def is_allowed_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").casefold() in ALLOWED_HOSTS


def _manifest_entries() -> list[dict[str, Any]]:
    return [dict(item) for item in MANIFEST if item.get("verified") and item.get("character") and item.get("quote")]


class StartupPreferences:
    KEY_DATE = "startup/last_shown_date"
    KEY_BAG = "startup/shuffle_bag"

    def __init__(self, settings: QSettings) -> None:
        self.settings = settings

    def should_show(self, mode: str, *, today: date | None = None) -> bool:
        if mode == "always":
            return True
        if mode == "off":
            return False
        return self.settings.value(self.KEY_DATE, "", type=str) != (today or date.today()).isoformat()

    def mark_shown(self, *, today: date | None = None) -> None:
        self.settings.setValue(self.KEY_DATE, (today or date.today()).isoformat())
        self.settings.sync()

    def take_entry(self, entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
        available = {str(item["id"]): dict(item) for item in entries}
        if not available:
            return fallback_content()
        try:
            bag = json.loads(self.settings.value(self.KEY_BAG, "[]", type=str))
        except (TypeError, ValueError, json.JSONDecodeError):
            bag = []
        bag = [item for item in bag if item in available]
        if not bag:
            bag = list(available)
            random.SystemRandom().shuffle(bag)
        selected = bag.pop(0)
        self.settings.setValue(self.KEY_BAG, json.dumps(bag, ensure_ascii=False))
        self.settings.sync()
        return available[selected]


def choose_startup_content(settings: QSettings) -> dict[str, Any]:
    return StartupPreferences(settings).take_entry(_manifest_entries())


def fallback_content() -> dict[str, Any]:
    return {
        "id": "fallback",
        "character": "RHINE LAB / LOCAL CACHE",
        "faction": "LATTICE",
        "quote": "LOCAL SYSTEM READY / OFFLINE VISUAL FALLBACK",
        "quote_zh": "本地系统已就绪 / 离线视觉回退",
        "quote_en": "Local system ready / offline visual fallback",
        "image_url": "",
        "source_url": "",
        "copyright": "Lattice original fallback",
    }


def validate_image_payload(payload: bytes, content_type: str | None = None) -> tuple[str, int, int]:
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("启动图片超过大小限制")
    detected = (content_type or "").split(";", 1)[0].strip().casefold()
    if detected and detected not in ALLOWED_MIME:
        raise ValueError("启动图片 MIME 类型不在白名单")
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
        width = int.from_bytes(payload[16:20], "big") if len(payload) >= 24 else 0
        height = int.from_bytes(payload[20:24], "big") if len(payload) >= 24 else 0
    elif payload.startswith(b"\xff\xd8\xff"):
        mime, width, height = "image/jpeg", 0, 0
    elif payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        mime, width, height = "image/webp", 0, 0
    else:
        raise ValueError("启动图片文件头无效")
    if detected and detected != mime:
        raise ValueError("启动图片 MIME 与文件内容不一致")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError("启动图片尺寸超过限制")
    return mime, width, height


def _decode_image(payload: bytes) -> QImage:
    image = QImage.fromData(payload)
    if image.isNull():
        raise ValueError("启动图片无法解码")
    if image.width() > MAX_IMAGE_DIMENSION or image.height() > MAX_IMAGE_DIMENSION:
        raise ValueError("启动图片尺寸超过限制")
    if max(image.width(), image.height()) > MAX_CACHED_IMAGE_DIMENSION:
        image = image.scaled(
            MAX_CACHED_IMAGE_DIMENSION,
            MAX_CACHED_IMAGE_DIMENSION,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


def image_cache_path(cache_dir: Path, entry: dict[str, Any]) -> Path:
    entry_id = str(entry.get("id", "")).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", entry_id):
        raise ValueError("启动素材 ID 无效")
    return Path(cache_dir) / f"{entry_id}.png"


def cached_image_url(cache_dir: Path, entry: dict[str, Any]) -> str:
    try:
        path = image_cache_path(cache_dir, entry)
    except ValueError:
        return ""
    if not path.is_file():
        return ""
    image = QImage(str(path))
    if image.isNull() or image.width() > MAX_CACHED_IMAGE_DIMENSION or image.height() > MAX_CACHED_IMAGE_DIMENSION:
        path.unlink(missing_ok=True)
        return ""
    return path.resolve().as_uri()


def download_image(url: str, destination: Path, *, sha256: str = "", timeout: float = 8.0) -> Path:
    if not is_allowed_url(url):
        raise ValueError("启动图片来源域名不在官方白名单")
    request = urllib.request.Request(url, headers={"User-Agent": "Lattice/0.2 (+offline-first)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
    validate_image_payload(payload, content_type)
    digest = hashlib.sha256(payload).hexdigest()
    if sha256 and digest.casefold() != sha256.casefold():
        raise ValueError("启动图片校验和不匹配")
    image = _decode_image(payload)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if not image.save(str(temporary), "PNG"):
        raise ValueError("启动图片缓存写入失败")
    temporary.replace(destination)
    return destination


def clear_cache(cache_dir: Path) -> int:
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return 0
    removed = 0
    for path in cache_dir.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
            removed += 1
        elif path.is_dir():
            shutil.rmtree(path)
            removed += 1
    return removed


class _ImageTaskSignals(QObject):
    ready = Signal(str, object)
    failed = Signal(str, object)


class StartupImageTask(QRunnable):
    """Download one manifest image without blocking the Qt GUI thread."""

    def __init__(self, entry: dict[str, Any], cache_dir: Path) -> None:
        super().__init__()
        self.entry = dict(entry)
        self.cache_dir = Path(cache_dir)
        self.signals = _ImageTaskSignals()

    def run(self) -> None:
        try:
            cached = cached_image_url(self.cache_dir, self.entry)
            if cached:
                self.signals.ready.emit(cached, self)
                return
            url = str(self.entry.get("image_url", ""))
            if not url:
                return
            path = download_image(
                url,
                image_cache_path(self.cache_dir, self.entry),
                sha256=str(self.entry.get("image_sha256", "")),
            )
            self.signals.ready.emit(path.resolve().as_uri(), self)
        except Exception as exc:  # Network and decoder failures use the visual fallback.
            self.signals.failed.emit(str(exc), self)


def create_image_task(entry: dict[str, Any], cache_dir: Path) -> StartupImageTask:
    return StartupImageTask(entry, cache_dir)
