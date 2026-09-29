"""
Unit tests for SAEngine Code Studio components:
- Code Editor & Tab Manager
- Find and Replace
- Syntax Highlighting
- File Explorer & Filter Proxy
- Terminal & Python REPL
- Git Service & Source Control Panel
- Script Runner
"""

import os
os.environ["QT_API"] = "pyside6"

from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor

from saengine.gui.editor.syntax_highlighter import (
    PythonHighlighter, JsonHighlighter, DiffHighlighter,
    MarkdownHighlighter, get_highlighter_for_file
)
from saengine.gui.editor.code_editor import CodeEditor, EditorTabWidget
from saengine.gui.editor.find_replace import FindReplaceBar
from saengine.gui.editor.file_explorer import FileExplorerPanel, FileFilterProxyModel
from saengine.gui.editor.terminal import TerminalWidget, ShellTerminal, PythonConsole
from saengine.gui.editor.git_panel import GitPanel, GitService
from saengine.gui.editor.script_runner import ScriptRunner
from saengine.gui.editor.script_templates import TEMPLATES
from saengine.core.project import Project
from saengine.commands.command_manager import CommandManager


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication is running."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_syntax_highlighters(qapp):
    editor = CodeEditor()
    doc = editor.document()

    # Python
    py_hl = PythonHighlighter(doc)
    doc.setPlainText("def analyze_frame(node_id: int):\n    # OpenSeesPy comment\n    model('basic')\n    return 42\n")
    assert py_hl is not None

    # Factory function
    hl_py = get_highlighter_for_file(Path("script.py"), doc)
    assert isinstance(hl_py, PythonHighlighter)

    hl_json = get_highlighter_for_file(Path("model.json"), doc)
    assert isinstance(hl_json, JsonHighlighter)

    hl_diff = get_highlighter_for_file(Path("changes.diff"), doc)
    assert isinstance(hl_diff, DiffHighlighter)

    hl_md = get_highlighter_for_file(Path("README.md"), doc)
    assert isinstance(hl_md, MarkdownHighlighter)


def test_code_editor_operations(qapp, tmp_path):
    editor = CodeEditor()
    editor.setPlainText("line 1\nline 2\nline 3")
    assert editor.blockCount() == 3

    # Test Line duplication
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    editor.duplicate_line()
    assert editor.blockCount() == 4

    # Test Line deletion
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    editor.delete_current_line()
    assert editor.blockCount() == 3

    # Test Comment toggle
    editor.setPlainText("x = 10\ny = 20")
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    editor.toggle_comment()
    assert editor.document().firstBlock().text().startswith("# ")
    # Toggle again to uncomment
    editor.toggle_comment()
    assert editor.document().firstBlock().text().startswith("x = 10")

    # Test Zoom
    initial_size = editor.font().pointSize()
    editor.zoom_in()
    assert editor.font().pointSize() == initial_size + 1
    editor.zoom_out()
    assert editor.font().pointSize() == initial_size

    # Test save and load
    test_file = tmp_path / "test_script.py"
    editor.setPlainText("print('Hello from SAEngine')")
    assert editor.save_file(test_file)
    assert test_file.exists()

    editor2 = CodeEditor()
    assert editor2.load_file(test_file)
    assert "Hello from SAEngine" in editor2.toPlainText()


def test_find_replace(qapp):
    editor = CodeEditor()
    editor.setPlainText("beam_1 = 100\nbeam_2 = 200\ncolumn_1 = 300\nbeam_3 = 400")

    bar = FindReplaceBar()
    bar.set_editor(editor)

    bar.show_find("beam")
    assert bar.isVisible()

    # Find next
    found = bar.find_next()
    assert found
    assert editor.textCursor().hasSelection()
    assert editor.textCursor().selectedText() == "beam"

    # Replace
    bar.show_replace("beam")
    bar.edit_replace.setText("girder")
    bar.replace()
    assert "girder_1" in editor.toPlainText()

    # Replace all
    bar.replace_all()
    assert "beam" not in editor.toPlainText()
    assert "girder_2" in editor.toPlainText()
    assert "girder_3" in editor.toPlainText()

    bar.close_bar()
    assert not bar.isVisible()


def test_editor_tab_widget(qapp, tmp_path):
    tab_widget = EditorTabWidget()
    assert tab_widget.tabs.count() >= 1

    # New file
    ed = tab_widget.new_file("analysis.py", initial_code="import openseespy.opensees as ops\n")
    assert tab_widget.current_editor() == ed
    assert "openseespy" in ed.toPlainText()

    # Templates
    assert len(TEMPLATES) >= 4
    assert "OpenSees 2D Portal Frame" in TEMPLATES

    # Run script signal
    received = []
    tab_widget.run_script_requested.connect(lambda c, p: received.append((c, p)))
    tab_widget.run_current_script()
    assert len(received) == 1
    assert "openseespy" in received[0][0]


def test_file_explorer(qapp, tmp_path):
    # Setup test dir
    (tmp_path / "model.py").write_text("print('model')")
    (tmp_path / "subfolder").mkdir()
    (tmp_path / "subfolder" / "data.json").write_text("{}")
    (tmp_path / ".venv").mkdir()

    panel = FileExplorerPanel(root_path=tmp_path)
    assert panel.root_path == tmp_path

    # Check proxy filtering excludes .venv
    assert ".venv" in FileFilterProxyModel.EXCLUDED_NAMES


def test_terminal_and_repl(qapp):
    term = TerminalWidget()
    assert term.tabs.count() == 2

    # REPL execution
    proj = Project.create_new("Test Tower")
    cmd_mgr = CommandManager()
    repl = term.python_console
    repl.update_context({"project": proj, "cmd_manager": cmd_mgr})

    repl.repl_input.setText("x = 100 * 2")
    repl._execute_line()
    assert repl.env.get("x") == 200

    repl.repl_input.setText("proj_name = project.settings.project_name")
    repl._execute_line()
    assert repl.env.get("proj_name") == "Test Tower"


def test_git_service_and_panel(qapp):
    git = GitService(Path.cwd())
    assert git.is_git_repo()

    branch = git.get_current_branch()
    assert branch != "unknown"

    status = git.get_status()
    assert "staged" in status
    assert "unstaged" in status
    assert "untracked" in status

    panel = GitPanel()
    assert panel.git.is_git_repo()
    assert panel.combo_branch.count() > 0


def test_script_runner(qapp):
    runner = ScriptRunner()
    proj = Project.create_new("Script Building")

    context = {
        "project": proj,
        "flag": False,
    }

    code = "flag = True\nproject.settings.project_name = 'Modified by Script'\n"

    outputs = []
    runner.output_received.connect(lambda txt, lvl: outputs.append((txt, lvl)))

    exit_code = runner.execute_in_engine(code, context)
    assert exit_code == 0
    assert context["project"].settings.project_name == "Modified by Script"
