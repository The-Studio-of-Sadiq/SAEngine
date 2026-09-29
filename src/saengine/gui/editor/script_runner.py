"""
Script Runner for SAEngine Code Studio.

Executes automation scripts either:
1. In-process: with direct access to 'project', 'cmd_manager', 'viewport', and 'ops',
   enabling parametric scripts to update the 3D model in real time.
2. Subprocess: via QProcess in a dedicated background worker with live output streaming.
"""

from __future__ import annotations

import sys
import os
import io
import contextlib
import traceback
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import QObject, Signal, QProcess, QByteArray


class ScriptRunner(QObject):
    """
    Executes Python and OpenSeesPy scripts.
    """

    started = Signal()
    output_received = Signal(str, str)  # (text, level: 'info', 'success', 'warning', 'error')
    finished = Signal(int)              # exit_code
    model_modified = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.process: Optional[QProcess] = None

    def execute_in_engine(self, code: str, context: Dict[str, Any], file_path: Optional[Path] = None) -> int:
        """
        Execute code synchronously inside the engine's Python process.
        Gives the script direct access to the live model, project, and OpenSeesPy.
        """
        self.started.emit()
        self.output_received.emit(
            f"--- Running in SAEngine Engine [Python {sys.version.split()[0]}] ---\n",
            "info"
        )

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        exec_globals = dict(context)
        exec_globals["__file__"] = str(file_path) if file_path else "<saengine_script>"
        exec_globals["__name__"] = "__main__"

        # Auto import openseespy if available
        try:
            import openseespy.opensees as ops
            exec_globals["ops"] = ops
            exec_globals["opensees"] = ops
        except Exception:
            pass

        exit_code = 0
        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(code, exec_globals)

            out = stdout_buf.getvalue()
            err = stderr_buf.getvalue()

            if out:
                self.output_received.emit(out, "info")
            if err:
                self.output_received.emit(err, "warning")

            self.output_received.emit("--- Script finished successfully ---\n", "success")
            self.model_modified.emit()
        except Exception:
            err_msg = traceback.format_exc()
            self.output_received.emit(err_msg, "error")
            exit_code = 1

        self.finished.emit(exit_code)
        return exit_code

    def execute_in_subprocess(self, file_path: Path, cwd: Optional[Path] = None) -> None:
        """
        Execute a script in a background Python process via QProcess.
        """
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.process.waitForFinished(1000)

        self.started.emit()
        self.output_received.emit(f"--- Running {file_path.name} in background ---\n", "info")

        self.process = QProcess(self)
        if cwd:
            self.process.setWorkingDirectory(str(cwd))

        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        python_exe = sys.executable
        self.process.start(python_exe, ["-u", str(file_path)])

    def _on_stdout(self) -> None:
        if self.process:
            data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            self.output_received.emit(data, "info")

    def _on_stderr(self) -> None:
        if self.process:
            data = self.process.readAllStandardError().data().decode("utf-8", errors="replace")
            self.output_received.emit(data, "error")

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        level = "success" if exit_code == 0 else "error"
        self.output_received.emit(f"\n--- Process exited with code {exit_code} ---\n", level)
        self.finished.emit(exit_code)

    def stop(self) -> None:
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.output_received.emit("\n--- Execution stopped by user ---\n", "warning")
