"""
VS Code Server Manager for SAEngine.

Manages the lifecycle of a local VS Code web server instance
(``code serve-web``) that runs in the background and provides
the full VS Code experience inside a QWebEngineView.
"""

from __future__ import annotations

import atexit
import logging
import re
import socket
import subprocess
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ServerMonitorThread(QThread):
    """
    Background thread that monitors the VS Code server process stdout/stderr
    to detect when the server is ready and capture its URL.
    """

    server_ready = Signal(str)        # Emits the URL when the server is ready
    server_error = Signal(str)        # Emits error messages
    server_output = Signal(str)       # Emits all stdout/stderr for logging

    def __init__(self, process: subprocess.Popen, expected_port: int, parent=None):
        super().__init__(parent)
        self._process = process
        self._expected_port = expected_port
        self._running = True

    def run(self):
        """Read process output line by line and detect the ready URL."""
        url_pattern = re.compile(r"(https?://\S+)")
        ready = False

        try:
            for line in iter(self._process.stdout.readline, ""):
                if not self._running:
                    break

                line = line.strip()
                if not line:
                    continue

                self.server_output.emit(line)
                logger.debug("code serve-web: %s", line)

                # Detect the server URL
                if not ready and ("Web UI available" in line or f":{self._expected_port}" in line):
                    match = url_pattern.search(line)
                    if match:
                        self.server_ready.emit(match.group(1))
                        ready = True
                    elif not ready:
                        # Fallback: construct URL ourselves
                        url = f"http://localhost:{self._expected_port}"
                        self.server_ready.emit(url)
                        ready = True

        except Exception as e:
            self.server_error.emit(str(e))

    def stop(self):
        self._running = False


class VSCodeServerManager(QObject):
    """
    Manages the ``code serve-web`` process lifecycle.

    Signals
    -------
    ready : str
        Emitted with the server URL when VS Code web is ready to use.
    error : str
        Emitted when the server encounters a fatal error.
    log_message : str
        Emitted for each line of server output (for the log panel).
    """

    ready = Signal(str)
    error = Signal(str)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[subprocess.Popen] = None
        self._monitor: Optional[_ServerMonitorThread] = None
        self._port: int = 0
        self._url: Optional[str] = None
        self._code_path: Optional[str] = None

        # Ensure we clean up on exit
        atexit.register(self.stop)

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> Optional[str]:
        return self._url

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _find_code_cli(self) -> Optional[str]:
        """Locate the ``code`` CLI executable."""
        code_path = shutil.which("code")
        if code_path:
            return code_path

        # Try common Windows install locations
        if sys.platform == "win32":
            candidates = [
                Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                Path("C:/Program Files/Microsoft VS Code/bin/code.cmd"),
                Path("C:/Program Files (x86)/Microsoft VS Code/bin/code.cmd"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)

        return None

    def start(self, workspace_folder: Optional[str] = None, port: int = 0) -> None:
        """
        Start the VS Code web server.

        Parameters
        ----------
        workspace_folder : str, optional
            The default folder to open in VS Code.
        port : int, optional
            Port to listen on. If 0, a random free port is chosen.
        """
        if self.is_running:
            logger.warning("VS Code server is already running on port %d", self._port)
            if self._url:
                self.ready.emit(self._url)
            return

        # Find the code CLI
        self._code_path = self._find_code_cli()
        if not self._code_path:
            self.error.emit(
                "Could not find the 'code' CLI. Please install VS Code and ensure "
                "'code' is available on your PATH."
            )
            return

        # Pick a port
        self._port = port if port > 0 else _find_free_port()

        # Build the command
        cmd = [
            self._code_path,
            "serve-web",
            "--host", "127.0.0.1",
            "--port", str(self._port),
            "--without-connection-token",
            "--accept-server-license-terms",
            "--disable-telemetry",
        ]

        if workspace_folder:
            cmd.extend(["--default-folder", workspace_folder])

        logger.info("Starting VS Code web server: %s", " ".join(cmd))
        self.log_message.emit(f"Starting VS Code web server on port {self._port}...")

        try:
            # Use CREATE_NO_WINDOW on Windows to suppress console popup
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                creationflags=creation_flags,
            )

            # Start the monitor thread
            self._monitor = _ServerMonitorThread(self._process, self._port, parent=self)
            self._monitor.server_ready.connect(self._on_ready)
            self._monitor.server_error.connect(self._on_error)
            self._monitor.server_output.connect(self.log_message.emit)
            self._monitor.start()

        except FileNotFoundError:
            self.error.emit(
                f"Failed to start VS Code server. Command not found: {self._code_path}"
            )
        except Exception as e:
            self.error.emit(f"Failed to start VS Code server: {e}")

    def _on_ready(self, url: str) -> None:
        """Handle the server becoming ready."""
        self._url = url
        logger.info("VS Code web server ready at: %s", url)
        self.log_message.emit(f"VS Code web server ready at: {url}")
        self.ready.emit(url)

    def _on_error(self, message: str) -> None:
        """Handle server errors."""
        logger.error("VS Code server error: %s", message)
        self.error.emit(message)

    def stop(self) -> None:
        """Terminate the VS Code server process."""
        if self._monitor:
            self._monitor.stop()
            self._monitor.quit()
            self._monitor.wait(3000)
            self._monitor = None

        if self._process:
            logger.info("Stopping VS Code web server (PID %d)...", self._process.pid)
            self.log_message.emit("Stopping VS Code web server...")

            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=3)
            except Exception as e:
                logger.warning("Error stopping VS Code server: %s", e)
            finally:
                self._process = None
                self._url = None

    def restart(self, workspace_folder: Optional[str] = None) -> None:
        """Restart the VS Code server."""
        self.stop()
        self.start(workspace_folder=workspace_folder, port=self._port)
