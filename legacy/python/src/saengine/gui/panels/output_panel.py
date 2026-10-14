"""
Output Panel — message, log, and command output console.
"""

from __future__ import annotations

import time
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel
)


class OutputPanel(QWidget):
    """
    Dockable log & message console for analysis messages and command logs.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        # Header bar with clear button
        header_bar = QHBoxLayout()
        header = QLabel("LOG & OUTPUT")
        header.setObjectName("panelHeader")
        header.setStyleSheet("font-weight: bold; color: #9aa0a6; padding: 2px;")
        header_bar.addWidget(header)
        header_bar.addStretch()

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setMaximumWidth(60)
        self.btn_clear.clicked.connect(self.clear)
        header_bar.addWidget(self.btn_clear)
        self._layout.addLayout(header_bar)

        # Console text area
        self.console = QTextEdit(self)
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                background-color: #14161a;
                color: #e0e0e0;
                border: 1px solid #2d313a;
                border-radius: 4px;
            }
        """)
        self._layout.addWidget(self.console)

    def append_message(self, message: str, level: str = "info") -> None:
        """Append a timestamped message with color formatting."""
        timestamp = time.strftime("%H:%M:%S")
        color = "#9aa0a6"
        if level == "cmd":
            color = "#4FC3F7"   # Blue
        elif level == "success":
            color = "#81C784"   # Green
        elif level == "warning":
            color = "#FFB74D"   # Orange
        elif level == "error":
            color = "#E57373"   # Red

        html = f"<span style='color: #666;'>[{timestamp}]</span> <span style='color: {color};'>{message}</span>"
        self.console.append(html)

    def clear(self) -> None:
        """Clear the console."""
        self.console.clear()
