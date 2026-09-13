"""Use the native preference store in production and the configured test store."""
from PySide6.QtCore import QSettings


def application_settings() -> QSettings:
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "ToolDeck", "ToolDeck")
