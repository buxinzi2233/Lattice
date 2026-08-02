from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def create_tray(app: QApplication, window, bridge, icon: QIcon) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        bridge.set_tray_icon(None)
        return None

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Lattice 晶格中枢")
    menu = QMenu()
    show_action = QAction("显示 Lattice", menu)
    quit_action = QAction("退出晶格中枢", menu)
    menu.addAction(show_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)

    def show_window() -> None:
        window.showNormal()
        window.raise_()
        window.requestActivate()

    def quit_app() -> None:
        bridge.allow_exit()
        tray.hide()
        window.close()
        app.quit()

    show_action.triggered.connect(show_window)
    quit_action.triggered.connect(quit_app)
    tray.activated.connect(
        lambda reason: show_window() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
    )
    tray.show()
    bridge.set_tray_icon(tray)
    app.setQuitOnLastWindowClosed(False)
    return tray
