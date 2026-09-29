"""
SAEngine Code Studio — Integrated Code Editor, File Explorer, Terminal, and Git tools.
"""

from saengine.gui.editor.code_editor import CodeEditor, EditorTabWidget
from saengine.gui.editor.file_explorer import FileExplorerPanel
from saengine.gui.editor.terminal import TerminalWidget, ShellTerminal, PythonConsole
from saengine.gui.editor.git_panel import GitPanel, GitService
from saengine.gui.editor.script_runner import ScriptRunner
from saengine.gui.editor.syntax_highlighter import get_highlighter_for_file
from saengine.gui.editor.find_replace import FindReplaceBar

__all__ = [
    "CodeEditor",
    "EditorTabWidget",
    "FileExplorerPanel",
    "TerminalWidget",
    "ShellTerminal",
    "PythonConsole",
    "GitPanel",
    "GitService",
    "ScriptRunner",
    "get_highlighter_for_file",
    "FindReplaceBar",
]
