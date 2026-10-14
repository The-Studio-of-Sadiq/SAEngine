"""
VS Code Web View Widget for SAEngine.

A QWebEngineView wrapper that displays the embedded VS Code web instance
and provides Python ↔ JavaScript communication via QWebChannel.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, Slot, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QStackedWidget
)

logger = logging.getLogger(__name__)


class _VSCodePage(QWebEnginePage):
    """
    Custom QWebEnginePage that handles VS Code-specific requirements:
    - Allows all keyboard shortcuts to pass through
    - Handles permission requests (clipboard, etc.)
    """

    def __init__(self, profile: QWebEngineProfile, parent=None):
        super().__init__(profile, parent)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        """Accept all navigation from the VS Code server."""
        return True


class _LoadingWidget(QWidget):
    """
    Splash/loading screen shown while VS Code server is starting up.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #1e1e1e;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        # Logo / Title
        self._title = QLabel("SAEngine")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("""
            QLabel {
                color: #4FC3F7;
                font-size: 36px;
                font-weight: bold;
                font-family: 'Segoe UI', 'Consolas', monospace;
                letter-spacing: 2px;
            }
        """)
        layout.addWidget(self._title)

        # Subtitle
        self._subtitle = QLabel("Structure Analysis Engine")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setStyleSheet("""
            QLabel {
                color: #9aa0a6;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        layout.addWidget(self._subtitle)

        # Status message
        self._status = QLabel("Starting VS Code environment...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                margin-top: 30px;
            }
        """)
        layout.addWidget(self._status)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # Indeterminate
        self._progress.setFixedWidth(300)
        self._progress.setFixedHeight(3)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: #333333;
                border: none;
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4FC3F7, stop:1 #0288D1);
                border-radius: 1px;
            }
        """)
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def set_error(self, message: str) -> None:
        self._status.setText(f"⚠ {message}")
        self._status.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                margin-top: 30px;
            }
        """)
        self._progress.hide()


class VSCodeWebView(QWidget):
    """
    Widget that embeds VS Code via QWebEngineView.

    Shows a loading screen while the server starts, then switches
    to the full VS Code web interface.

    Signals
    -------
    editor_loaded : None
        Emitted when VS Code is fully loaded and interactive.
    editor_error : str
        Emitted when the editor fails to load.
    """

    editor_loaded = Signal()
    editor_error = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Stacked widget: loading screen (0) ↔ web view (1)
        self._stack = QStackedWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack)

        # Loading screen
        self._loading = _LoadingWidget()
        self._stack.addWidget(self._loading)

        # Create a dedicated profile for the VS Code session
        self._profile = QWebEngineProfile("saengine-vscode", self)
        self._profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

        # Web view
        self._page = _VSCodePage(self._profile)
        self._web_view = QWebEngineView()
        self._web_view.setPage(self._page)

        # Configure web engine settings for VS Code compatibility
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, True)

        self._stack.addWidget(self._web_view)

        # Start on loading screen
        self._stack.setCurrentIndex(0)

        # Track loading
        self._page.loadFinished.connect(self._on_load_finished)

        # Retry timer
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(2000)
        self._retry_timer.timeout.connect(self._retry_load)
        self._retry_count = 0
        self._max_retries = 15
        self._target_url: Optional[str] = None

    def load_url(self, url: str) -> None:
        """Load the VS Code server URL, with automatic retry logic."""
        self._target_url = url
        self._retry_count = 0
        self._loading.set_status(f"Connecting to VS Code at {url}...")
        logger.info("Loading VS Code URL: %s", url)
        self._web_view.setUrl(QUrl(url))

    def _retry_load(self) -> None:
        """Retry loading the URL if it failed (server may still be starting)."""
        if self._retry_count >= self._max_retries:
            self._retry_timer.stop()
            msg = "Failed to connect to VS Code server after multiple attempts."
            self._loading.set_error(msg)
            self.editor_error.emit(msg)
            return

        self._retry_count += 1
        self._loading.set_status(
            f"Retrying connection (attempt {self._retry_count}/{self._max_retries})..."
        )
        logger.debug("Retry #%d loading %s", self._retry_count, self._target_url)
        self._web_view.setUrl(QUrl(self._target_url))

    def _on_load_finished(self, ok: bool) -> None:
        """Handle page load completion."""
        if ok:
            self._retry_timer.stop()
            logger.info("VS Code web UI loaded successfully")
            self._loading.set_status("VS Code loaded!")

            # Give VS Code a moment to fully initialize, then switch
            QTimer.singleShot(500, self._show_editor)
        else:
            # Start or continue retry timer
            if not self._retry_timer.isActive():
                self._retry_timer.start()

    def _show_editor(self) -> None:
        """Switch from loading screen to the VS Code web view."""
        self._stack.setCurrentIndex(1)
        self._web_view.setFocus()
        self.editor_loaded.emit()

    def update_status(self, message: str) -> None:
        """Update the loading screen status message."""
        self._loading.set_status(message)

    def show_error(self, message: str) -> None:
        """Show an error on the loading screen."""
        self._loading.set_error(message)
        self._stack.setCurrentIndex(0)

    def reload(self) -> None:
        """Reload the VS Code web view."""
        self._web_view.reload()

    def navigate_to(self, url: str) -> None:
        """Navigate to a specific URL in the web view."""
        self._web_view.setUrl(QUrl(url))
