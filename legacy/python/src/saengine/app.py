"""
SAEngine Application Bootstrap.

Initializes QApplication with WebEngine support, loads the modern
CAD dark theme, and launches the VS Code-integrated MainWindow.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# WebEngine must be imported before QApplication is created
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import QApplication

from saengine.gui.main_window import MainWindow


def load_theme(app: QApplication, theme_name: str = "dark") -> None:
    """Load a QSS stylesheet from gui/themes/."""
    theme_path = Path(__file__).parent / "gui" / "themes" / f"{theme_name}.qss"
    if theme_path.exists():
        with open(theme_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


def main() -> int:
    """Application entry point."""
    # Ensure High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SAEngine")
    app.setOrganizationName("SAEngine")
    app.setApplicationVersion("0.1.0")

    # Set default modern font
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    # Apply professional dark theme
    load_theme(app, "dark")

    # Create and display the main window
    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
