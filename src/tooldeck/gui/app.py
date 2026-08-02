from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .bridge import AppBridge
from .tray import create_tray


def icon_path() -> Path:
    assets = Path(__file__).with_name("assets")
    return assets / ("lattice.ico" if sys.platform == "win32" else "lattice-mark.svg")


def qml_path() -> Path:
    return Path(__file__).with_name("qml") / "Main.qml"


def fonts_dir() -> Path:
    return Path(__file__).with_name("assets") / "fonts"


def register_fonts() -> None:
    for suffix in ("*.ttf", "*.otf"):
        for font in fonts_dir().glob(suffix):
            QFontDatabase.addApplicationFont(str(font))


def create_engine(bridge: AppBridge | None = None) -> tuple[QQmlApplicationEngine, AppBridge]:
    selected_bridge = bridge or AppBridge()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(qml_path().parent))
    engine.rootContext().setContextProperty("AppBridge", selected_bridge)
    engine.load(QUrl.fromLocalFile(str(qml_path())))
    return engine, selected_bridge


def run_gui() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Lattice")
    app.setApplicationDisplayName("Lattice 晶格中枢")
    app.setOrganizationName("ToolDeck")
    app.setDesktopFileName("tooldeck")
    icon = QIcon(str(icon_path()))
    app.setWindowIcon(icon)
    register_fonts()
    QQuickStyle.setStyle("Basic")

    bridge = AppBridge()
    bridge.setStartupAutoLaunch(True)
    engine, bridge = create_engine(bridge)
    if not engine.rootObjects():
        bridge.shutdown()
        return 1
    window = engine.rootObjects()[0]
    tray = create_tray(app, window, bridge, icon)

    def request_exit() -> None:
        bridge.allow_exit()
        if tray is not None:
            tray.hide()
        window.close()
        app.quit()

    bridge.exitRequested.connect(request_exit)
    QTimer.singleShot(0, bridge.startAutostart)
    exit_code = app.exec()
    bridge.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_gui())
