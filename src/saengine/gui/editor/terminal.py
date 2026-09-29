"""
Integrated Terminal & Scripting Console for SAEngine Code Studio.

Provides:
1. Shell Terminal: Real interactive terminal (PowerShell/cmd/bash) via QProcess
   with command history, real-time streaming, and working directory tracking.
2. Interactive Python REPL: Live console executing against the active SAEngine
   project and OpenSeesPy model state.
"""

from __future__ import annotations

import sys
import os
import io
import contextlib
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Signal, QProcess, QByteArray
from PySide6.QtGui import QFont, QTextCursor, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QToolButton, QLabel, QTabWidget, QSizePolicy
)


class ShellTerminal(QWidget):
    """
    Subprocess-driven interactive command shell (PowerShell / cmd on Windows).
    """

    def __init__(self, cwd: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.cwd = cwd or Path.cwd()
        self.history: List[str] = []
        self.history_index = -1
        self.process: Optional[QProcess] = None

        self._build_ui()
        self._start_shell()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 1. Output Screen
        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: #101216;
                color: #d4d4d4;
                font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid #2d313a;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.output_text, 1)

        # 2. Input row & actions
        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        self.lbl_prompt = QLabel(self._get_prompt_text())
        self.lbl_prompt.setStyleSheet("color: #81C784; font-weight: bold; font-family: monospace; font-size: 12px;")
        input_row.addWidget(self.lbl_prompt)

        self.cmd_input = QLineEdit(self)
        self.cmd_input.setPlaceholderText("Type a command (e.g. git status, python script.py, pytest)...")
        self.cmd_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1d23;
                color: #e8eaed;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 12px;
                border: 1px solid #2d313a;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                border-color: #4FC3F7;
            }
        """)
        self.cmd_input.returnPressed.connect(self._on_command_entered)
        # Custom key handling for Up/Down history
        self.cmd_input.installEventFilter(self)
        input_row.addWidget(self.cmd_input, 1)

        # Stop / Interrupt
        self.btn_interrupt = QToolButton(self)
        self.btn_interrupt.setText("■ Stop")
        self.btn_interrupt.setToolTip("Interrupt running command (Ctrl+C)")
        self.btn_interrupt.setStyleSheet("""
            QToolButton {
                background-color: #3e1b1b;
                color: #E57373;
                border: 1px solid #5a2323;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }
            QToolButton:hover {
                background-color: #5a2323;
                color: #ffffff;
            }
        """)
        self.btn_interrupt.clicked.connect(self.interrupt)
        input_row.addWidget(self.btn_interrupt)

        # Clear
        btn_clear = QToolButton(self)
        btn_clear.setText("Clear")
        btn_clear.setToolTip("Clear terminal output")
        btn_clear.clicked.connect(self.clear)
        input_row.addWidget(btn_clear)

        layout.addLayout(input_row)

        # 3. Quick Command Bar
        quick_bar = QHBoxLayout()
        quick_bar.setSpacing(6)

        lbl_quick = QLabel("Quick:")
        lbl_quick.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        quick_bar.addWidget(lbl_quick)

        for cmd_name, cmd_str in [
            ("git status", "git status"),
            ("git diff", "git diff"),
            ("git log", "git log -n 5 --oneline"),
            ("python -V", f'"{sys.executable}" -V'),
            ("pytest (unit)", f'"{sys.executable}" -m pytest tests/unit/test_grids.py tests/unit/test_stories.py tests/unit/test_units.py'),
        ]:
            btn = QToolButton(self)
            btn.setText(cmd_name)
            btn.setStyleSheet("""
                QToolButton {
                    background-color: #1e2128;
                    color: #9aa0a6;
                    border: 1px solid #2d313a;
                    border-radius: 3px;
                    padding: 2px 6px;
                    font-size: 10px;
                }
                QToolButton:hover {
                    color: #4FC3F7;
                    border-color: #4FC3F7;
                }
            """)
            btn.clicked.connect(lambda checked=False, c=cmd_str: self.run_command(c))
            quick_bar.addWidget(btn)

        quick_bar.addStretch()
        layout.addLayout(quick_bar)

    def _get_prompt_text(self) -> str:
        name = self.cwd.name or str(self.cwd)
        return f"{name} >"

    def set_cwd(self, path: Path) -> None:
        self.cwd = Path(path).resolve()
        self.lbl_prompt.setText(self._get_prompt_text())
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.setWorkingDirectory(str(self.cwd))

    def _start_shell(self) -> None:
        self.append_output("SAEngine Shell Terminal Ready.\nType commands or use quick actions.\n\n", color="#4FC3F7")

    def _on_command_entered(self) -> None:
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return

        self.cmd_input.clear()
        self.history.append(cmd)
        self.history_index = len(self.history)

        self.run_command(cmd)

    def run_command(self, cmd: str) -> None:
        # Echo command
        self.append_output(f"\n{self._get_prompt_text()} {cmd}\n", color="#81C784")

        # Built-in 'cd' handling
        parts = cmd.split(maxsplit=1)
        if parts[0].lower() == "cd":
            if len(parts) > 1:
                target = (self.cwd / parts[1].strip('"')).resolve()
                if target.exists() and target.is_dir():
                    self.set_cwd(target)
                else:
                    self.append_output(f"Directory not found: {parts[1]}\n", color="#E57373")
            return
        elif parts[0].lower() == "clear" or parts[0].lower() == "cls":
            self.clear()
            return

        # Execute via QProcess
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.process.waitForFinished(1000)

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(self.cwd))
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        # Launch via shell
        if sys.platform == "win32":
            # Use cmd.exe /c
            self.process.start("cmd.exe", ["/c", cmd])
        else:
            self.process.start("/bin/sh", ["-c", cmd])

    def _on_stdout(self) -> None:
        if self.process:
            data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            self.append_output(data)

    def _on_stderr(self) -> None:
        if self.process:
            data = self.process.readAllStandardError().data().decode("utf-8", errors="replace")
            self.append_output(data, color="#E57373")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if exit_code != 0:
            self.append_output(f"[Process exited with code {exit_code}]\n", color="#FFB74D")

    def interrupt(self) -> None:
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.append_output("\n^C [Process terminated]\n", color="#E57373")

    def clear(self) -> None:
        self.output_text.clear()

    def append_output(self, text: str, color: Optional[str] = None) -> None:
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color:
            html = f"<span style='color: {color}; white-space: pre-wrap;'>{self._escape(text)}</span>"
            cursor.insertHtml(html)
        else:
            cursor.insertText(text)
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

    def _escape(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    def eventFilter(self, obj, event) -> bool:
        if obj == self.cmd_input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                if self.history and self.history_index > 0:
                    self.history_index -= 1
                    self.cmd_input.setText(self.history[self.history_index])
                return True
            elif event.key() == Qt.Key.Key_Down:
                if self.history and self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.cmd_input.setText(self.history[self.history_index])
                elif self.history_index >= len(self.history) - 1:
                    self.history_index = len(self.history)
                    self.cmd_input.clear()
                return True
        return super().eventFilter(obj, event)


class PythonConsole(QWidget):
    """
    Interactive Python REPL console executing in the live SAEngine application context.
    Provides immediate access to 'project', 'cmd_manager', 'opensees', and 'app'.
    """

    def __init__(self, env_context: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.env: Dict[str, Any] = env_context or {}
        self.history: List[str] = []
        self.history_index = -1

        # Setup default modules in REPL
        try:
            import openseespy.opensees as ops
            self.env['ops'] = ops
            self.env['opensees'] = ops
        except Exception:
            pass

        self._build_ui()
        self._welcome_message()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: #101216;
                color: #e8eaed;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 12px;
                border: 1px solid #2d313a;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.output_text, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        lbl = QLabel(">>>")
        lbl.setStyleSheet("color: #4FC3F7; font-weight: bold; font-family: monospace; font-size: 13px;")
        input_row.addWidget(lbl)

        self.repl_input = QLineEdit(self)
        self.repl_input.setPlaceholderText("Enter Python expression (e.g. project.grids.x_lines, ops.node(...))...")
        self.repl_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1d23;
                color: #e8eaed;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 12px;
                border: 1px solid #2d313a;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                border-color: #4FC3F7;
            }
        """)
        self.repl_input.returnPressed.connect(self._execute_line)
        self.repl_input.installEventFilter(self)
        input_row.addWidget(self.repl_input, 1)

        btn_clear = QToolButton(self)
        btn_clear.setText("Clear")
        btn_clear.clicked.connect(self.output_text.clear)
        input_row.addWidget(btn_clear)

        layout.addLayout(input_row)

    def update_context(self, new_context: Dict[str, Any]) -> None:
        """Update live objects exposed in the REPL."""
        self.env.update(new_context)

    def _welcome_message(self) -> None:
        self.append_text(
            f"SAEngine Interactive Python REPL [Python {sys.version.split()[0]}]\n"
            "Live Objects: 'project', 'cmd_manager', 'ops' (OpenSeesPy)\n"
            "Try: print(project.settings.project_name)\n\n",
            color="#4FC3F7"
        )

    def _execute_line(self) -> None:
        code = self.repl_input.text().strip()
        if not code:
            return

        self.repl_input.clear()
        self.history.append(code)
        self.history_index = len(self.history)

        self.append_text(f">>> {code}\n", color="#81C784")

        # Capture stdout & stderr
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                # Try evaluating as expression first
                try:
                    res = eval(code, self.env)
                    if res is not None:
                        print(repr(res))
                except SyntaxError:
                    # Execute as statement
                    exec(code, self.env)

            out = stdout_buf.getvalue()
            err = stderr_buf.getvalue()

            if out:
                self.append_text(out)
            if err:
                self.append_text(err, color="#E57373")
        except Exception:
            tb = traceback.format_exc()
            self.append_text(tb, color="#E57373")

    def append_text(self, text: str, color: Optional[str] = None) -> None:
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color:
            html = f"<span style='color: {color}; white-space: pre-wrap;'>{text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace(chr(10), '<br>')}</span>"
            cursor.insertHtml(html)
        else:
            cursor.insertText(text)
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

    def eventFilter(self, obj, event) -> bool:
        if obj == self.repl_input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                if self.history and self.history_index > 0:
                    self.history_index -= 1
                    self.repl_input.setText(self.history[self.history_index])
                return True
            elif event.key() == Qt.Key.Key_Down:
                if self.history and self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.repl_input.setText(self.history[self.history_index])
                elif self.history_index >= len(self.history) - 1:
                    self.history_index = len(self.history)
                    self.repl_input.clear()
                return True
        return super().eventFilter(obj, event)


class TerminalWidget(QWidget):
    """
    Combined Terminal dock widget featuring both a System Shell Terminal
    and a live Python Scripting REPL.
    """

    def __init__(self, cwd: Optional[Path] = None, env_context: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #101216;
            }
            QTabBar::tab {
                background-color: #1e2128;
                color: #9aa0a6;
                padding: 4px 12px;
                border: 1px solid #2d313a;
                border-bottom: none;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background-color: #101216;
                color: #4FC3F7;
                font-weight: bold;
                border-top: 2px solid #4FC3F7;
            }
        """)

        # Shell Terminal
        self.shell = ShellTerminal(cwd=cwd, parent=self)
        self.tabs.addTab(self.shell, "Terminal (Shell)")

        # Python Console
        self.python_console = PythonConsole(env_context=env_context, parent=self)
        self.tabs.addTab(self.python_console, "Python REPL")

        layout.addWidget(self.tabs)

    def set_cwd(self, path: Path) -> None:
        self.shell.set_cwd(path)

    def update_context(self, context: Dict[str, Any]) -> None:
        self.python_console.update_context(context)

    def run_command(self, cmd: str) -> None:
        self.tabs.setCurrentWidget(self.shell)
        self.shell.run_command(cmd)
