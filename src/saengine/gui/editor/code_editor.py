"""
Code Editor component for SAEngine Code Studio.

Provides an advanced, high-performance source code editor with:
- Line number gutter with active line indicator
- Current line highlighting and bracket matching
- Intelligent auto-indentation and tab handling (4 spaces)
- Code commenting (Ctrl+/), line duplication (Ctrl+D), line deletion
- Multi-tab file management with dirty indicators
- Integrated search and replace bar
- Zooming (Ctrl+Wheel / Ctrl++/Ctrl+-)
- Integrated syntax highlighting for Python/OpenSeesPy/JSON/Diffs
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import (
    QColor, QPainter, QTextFormat, QTextCursor, QFont,
    QKeyEvent, QWheelEvent, QKeySequence, QAction, QIcon
)
from PySide6.QtWidgets import (
    QWidget, QPlainTextEdit, QTextEdit, QVBoxLayout, QHBoxLayout,
    QTabWidget, QToolBar, QToolButton, QLabel, QFileDialog,
    QMessageBox, QMenu, QSplitter
)

from saengine.gui.editor.syntax_highlighter import get_highlighter_for_file
from saengine.gui.editor.find_replace import FindReplaceBar


class LineNumberArea(QWidget):
    """Gutter widget displaying line numbers for CodeEditor."""

    def __init__(self, editor: CodeEditor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.code_editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    """
    Core text editor widget customized for programming and structural modeling scripts.
    """

    cursor_position_changed = Signal(int, int)  # line (1-indexed), col (1-indexed)
    file_saved = Signal(Path)

    def __init__(self, file_path: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_path: Optional[Path] = file_path
        self._is_modified = False

        # Configure font
        font = QFont()
        font.setFamilies(["Cascadia Code", "Consolas", "Fira Code", "Courier New", "monospace"])
        font.setFixedPitch(True)
        font.setPointSize(11)
        self.setFont(font)

        # Tab stop = 4 spaces
        font_metrics = self.fontMetrics()
        self.setTabStopDistance(4 * font_metrics.horizontalAdvance(' '))

        # Editor configuration
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.line_number_area = LineNumberArea(self)

        # Connect signals
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.cursorPositionChanged.connect(self._emit_cursor_pos)
        self.modificationChanged.connect(self._on_modification_changed)

        # Styling
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #14161a;
                color: #e8eaed;
                border: none;
                selection-background-color: #264f78;
                selection-color: #ffffff;
            }
        """)

        # Setup highlighter
        self.highlighter = get_highlighter_for_file(self.file_path, self.document())

        self.update_line_number_area_width(0)
        self.highlight_current_line()

    # ── Line Number Gutter ───────────────────────────────────────

    def line_number_area_width(self) -> int:
        digits = max(1, len(str(max(1, self.blockCount()))))
        # Width: digits * char_width + padding
        space = 16 + self.fontMetrics().horizontalAdvance('9') * digits
        return max(42, space)

    def update_line_number_area_width(self, _) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        # Background
        painter.fillRect(event.rect(), QColor("#181b20"))

        # Right border line
        painter.setPen(QColor("#2d313a"))
        painter.drawLine(
            self.line_number_area.width() - 1, event.rect().top(),
            self.line_number_area.width() - 1, event.rect().bottom()
        )

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        current_block_num = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_block_num:
                    painter.setPen(QColor("#4FC3F7"))  # Highlight current line number
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(QColor("#5f6368"))  # Subtle line number
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)

                painter.drawText(
                    0, top, self.line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number
                )

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    # ── Active Line Highlighting ────────────────────────────────

    def highlight_current_line(self) -> None:
        extra_selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor("#1f242d")
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)

        self.setExtraSelections(extra_selections)

    def _emit_cursor_pos(self) -> None:
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        self.cursor_position_changed.emit(line, col)

    def _on_modification_changed(self, modified: bool) -> None:
        self._is_modified = modified

    # ── Keyboard & Indentation Logic ────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

        # Ctrl + / : Toggle Comment
        if key == Qt.Key.Key_Slash and (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.toggle_comment()
            event.accept()
            return

        # Ctrl + D : Duplicate Line / Selection
        if key == Qt.Key.Key_D and (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.duplicate_line()
            event.accept()
            return

        # Ctrl + Shift + K : Delete Line
        if key == Qt.Key.Key_K and (modifiers & Qt.KeyboardModifier.ControlModifier) and (modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.delete_current_line()
            event.accept()
            return

        # Tab: Insert 4 spaces or indent block
        if key == Qt.Key.Key_Tab and modifiers == Qt.KeyboardModifier.NoModifier:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self.indent_selection()
            else:
                cursor.insertText("    ")
            event.accept()
            return

        # Shift + Tab: Dedent block
        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and (modifiers & Qt.KeyboardModifier.ShiftModifier)):
            self.dedent_selection()
            event.accept()
            return

        # Enter: Auto-indentation
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._handle_auto_indent()
            event.accept()
            return

        # Auto-pair brackets & quotes
        auto_pairs = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
        char = event.text()
        if char in auto_pairs and not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            cursor = self.textCursor()
            if cursor.hasSelection():
                sel = cursor.selectedText()
                cursor.insertText(char + sel + auto_pairs[char])
                event.accept()
                return

        super().keyPressEvent(event)

    def _handle_auto_indent(self) -> None:
        cursor = self.textCursor()
        current_block = cursor.block()
        line_text = current_block.text()

        # Calculate leading whitespace
        indent_len = len(line_text) - len(line_text.lstrip())
        indent = line_text[:indent_len]

        # If line ends with ':', add 4 more spaces (Python block start)
        stripped = line_text.rstrip()
        if stripped.endswith(":"):
            indent += "    "

        cursor.insertText("\n" + indent)

    def indent_selection(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        start_block = cursor.blockNumber()
        cursor.setPosition(end)
        end_block = cursor.blockNumber()

        cursor.beginEditBlock()
        for b_idx in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(b_idx)
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            c.insertText("    ")
        cursor.endEditBlock()

    def dedent_selection(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        start_block = cursor.blockNumber()
        cursor.setPosition(end)
        end_block = cursor.blockNumber()

        cursor.beginEditBlock()
        for b_idx in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(b_idx)
            text = block.text()
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            spaces_to_remove = min(4, len(text) - len(text.lstrip(' ')))
            if spaces_to_remove > 0:
                for _ in range(spaces_to_remove):
                    c.deleteChar()
        cursor.endEditBlock()

    def toggle_comment(self) -> None:
        """Toggle '#' comment at the beginning of selected lines."""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        start_block = cursor.blockNumber()
        cursor.setPosition(end)
        end_block = cursor.blockNumber()

        cursor.beginEditBlock()
        # Check if all lines are already commented
        all_commented = True
        for b_idx in range(start_block, end_block + 1):
            b_text = self.document().findBlockByNumber(b_idx).text().strip()
            if b_text and not b_text.startswith("#"):
                all_commented = False
                break

        for b_idx in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(b_idx)
            text = block.text()
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            if all_commented:
                # Remove comment
                lstrip_len = len(text) - len(text.lstrip(' '))
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, lstrip_len)
                if text[lstrip_len:].startswith("# "):
                    c.deleteChar()
                    c.deleteChar()
                elif text[lstrip_len:].startswith("#"):
                    c.deleteChar()
            else:
                # Add comment
                c.insertText("# ")
        cursor.endEditBlock()

    def duplicate_line(self) -> None:
        """Duplicate current line or selection."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor)
            cursor.insertText(text)
        else:
            block = cursor.block()
            line_text = block.text()
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertText("\n" + line_text)

    def delete_current_line(self) -> None:
        """Delete the current line including newline."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor):
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.endEditBlock()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl + Wheel Zoom."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom_in(self) -> None:
        font = self.font()
        if font.pointSize() < 36:
            font.setPointSize(font.pointSize() + 1)
            self.setFont(font)
            self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(' '))
            self.update_line_number_area_width(0)

    def zoom_out(self) -> None:
        font = self.font()
        if font.pointSize() > 6:
            font.setPointSize(font.pointSize() - 1)
            self.setFont(font)
            self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(' '))
            self.update_line_number_area_width(0)

    # ── File Operations ──────────────────────────────────────────

    def load_file(self, file_path: Path) -> bool:
        """Load text file into editor."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.setPlainText(content)
            self.file_path = file_path
            self.document().setModified(False)
            self.highlighter = get_highlighter_for_file(self.file_path, self.document())
            return True
        except Exception as e:
            return False

    def save_file(self, file_path: Optional[Path] = None) -> bool:
        """Save editor text to file."""
        target = file_path or self.file_path
        if not target:
            return False
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(self.toPlainText())
            self.file_path = target
            self.document().setModified(False)
            self.highlighter = get_highlighter_for_file(self.file_path, self.document())
            self.file_saved.emit(target)
            return True
        except Exception:
            return False


class EditorTabWidget(QWidget):
    """
    Multi-tab source code editor manager with integrated toolbar, search,
    and status footer.
    """

    file_opened = Signal(Path)
    file_saved = Signal(Path)
    run_script_requested = Signal(str, Path)  # (code, file_path or empty)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._untitled_counter = 1
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Editor Toolbar
        self.toolbar = QToolBar(self)
        self.toolbar.setFixedHeight(34)
        self.toolbar.setMovable(False)
        self.toolbar.setStyleSheet("""
            QToolBar {
                background-color: #1e2128;
                border-bottom: 1px solid #2d313a;
                spacing: 2px;
                padding: 2px 6px;
            }
            QToolButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 3px 8px;
                color: #e8eaed;
                font-size: 11px;
            }
            QToolButton:hover {
                background-color: #2d313a;
                border-color: #353840;
            }
            QToolButton:pressed {
                background-color: #4FC3F7;
                color: #1a1d23;
            }
        """)

        # Run Action
        self.btn_run = QToolButton(self)
        self.btn_run.setText("▶ Run Script (F5)")
        self.btn_run.setStyleSheet("""
            QToolButton {
                background-color: #1b4d3e;
                color: #81C784;
                font-weight: bold;
                border: 1px solid #2e7d32;
                border-radius: 4px;
                padding: 3px 10px;
            }
            QToolButton:hover {
                background-color: #2e7d32;
                color: #ffffff;
            }
        """)
        self.btn_run.clicked.connect(self.run_current_script)
        self.toolbar.addWidget(self.btn_run)

        self.toolbar.addSeparator()

        # File actions
        btn_new = QToolButton(self)
        btn_new.setText("+ New")
        btn_new.setToolTip("New Script (Ctrl+N)")
        btn_new.clicked.connect(lambda: self.new_file())
        self.toolbar.addWidget(btn_new)

        btn_open = QToolButton(self)
        btn_open.setText("📂 Open")
        btn_open.setToolTip("Open File (Ctrl+O)")
        btn_open.clicked.connect(self.open_file_dialog)
        self.toolbar.addWidget(btn_open)

        btn_save = QToolButton(self)
        btn_save.setText("💾 Save")
        btn_save.setToolTip("Save Script (Ctrl+S)")
        btn_save.clicked.connect(self.save_current_file)
        self.toolbar.addWidget(btn_save)

        self.toolbar.addSeparator()

        # Find / Replace
        btn_find = QToolButton(self)
        btn_find.setText("🔍 Find")
        btn_find.setToolTip("Find in File (Ctrl+F)")
        btn_find.clicked.connect(self.toggle_find)
        self.toolbar.addWidget(btn_find)

        btn_replace = QToolButton(self)
        btn_replace.setText("🔁 Replace")
        btn_replace.setToolTip("Replace in File (Ctrl+H)")
        btn_replace.clicked.connect(self.toggle_replace)
        self.toolbar.addWidget(btn_replace)

        self.toolbar.addSeparator()

        # Templates Menu
        self.btn_templates = QToolButton(self)
        self.btn_templates.setText("📐 Templates ▾")
        self.btn_templates.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._build_template_menu()
        self.toolbar.addWidget(self.btn_templates)

        layout.addWidget(self.toolbar)

        # 2. Find and Replace Floating/Embedded Bar
        self.find_replace_bar = FindReplaceBar(self)
        layout.addWidget(self.find_replace_bar)

        # 3. Tab Widget
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #14161a;
            }
            QTabBar::tab {
                background-color: #1e2128;
                color: #9aa0a6;
                padding: 6px 14px;
                border: 1px solid #2d313a;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background-color: #14161a;
                color: #4FC3F7;
                border-top: 2px solid #4FC3F7;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background-color: #252830;
                color: #e8eaed;
            }
        """)
        layout.addWidget(self.tabs, 1)

        # 4. Status Footer
        self.footer = QWidget(self)
        self.footer.setFixedHeight(24)
        self.footer.setStyleSheet("""
            QWidget {
                background-color: #181b20;
                border-top: 1px solid #2d313a;
                color: #9aa0a6;
                font-size: 11px;
            }
        """)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(10, 0, 10, 0)
        footer_layout.setSpacing(16)

        self.lbl_cursor_pos = QLabel("Ln 1, Col 1")
        footer_layout.addWidget(self.lbl_cursor_pos)

        self.lbl_total_lines = QLabel("0 lines")
        footer_layout.addWidget(self.lbl_total_lines)

        footer_layout.addStretch()

        self.lbl_lang = QLabel("Python")
        footer_layout.addWidget(self.lbl_lang)

        self.lbl_indent = QLabel("Spaces: 4")
        footer_layout.addWidget(self.lbl_indent)

        self.lbl_encoding = QLabel("UTF-8")
        footer_layout.addWidget(self.lbl_encoding)

        layout.addWidget(self.footer)

        # Open default starting script
        self.new_file(initial_code="# SAEngine Structural Scripting Studio\n# Automate ETABS models & OpenSeesPy finite-element analysis\n\nimport openseespy.opensees as ops\nfrom saengine.core.project import Project\n\nprint('Ready to run structural scripts.')\n")

    def _build_template_menu(self) -> None:
        menu = QMenu(self)
        from saengine.gui.editor.script_templates import TEMPLATES

        for name, code in TEMPLATES.items():
            action = menu.addAction(name)
            action.triggered.connect(lambda checked=False, c=code, n=name: self._insert_template(n, c))

        self.btn_templates.setMenu(menu)

    def _insert_template(self, title: str, code: str) -> None:
        filename = title.lower().replace(" ", "_") + ".py"
        editor = self.new_file(title=filename, initial_code=code)

    def current_editor(self) -> Optional[CodeEditor]:
        idx = self.tabs.currentIndex()
        if idx >= 0:
            return self.tabs.widget(idx)
        return None

    def new_file(self, title: Optional[str] = None, initial_code: str = "") -> CodeEditor:
        if not title:
            title = f"script_{self._untitled_counter}.py"
            self._untitled_counter += 1

        editor = CodeEditor(parent=self)
        if initial_code:
            editor.setPlainText(initial_code)
            editor.document().setModified(False)

        editor.cursor_position_changed.connect(self._update_cursor_status)
        editor.document().modificationChanged.connect(lambda m: self._update_tab_title(editor))

        idx = self.tabs.addTab(editor, title)
        self.tabs.setCurrentIndex(idx)
        editor.setFocus()
        return editor

    def open_file(self, file_path: Path) -> Optional[CodeEditor]:
        # Check if already open
        for i in range(self.tabs.count()):
            ed = self.tabs.widget(i)
            if isinstance(ed, CodeEditor) and ed.file_path == file_path:
                self.tabs.setCurrentIndex(i)
                return ed

        editor = CodeEditor(file_path=file_path, parent=self)
        if editor.load_file(file_path):
            editor.cursor_position_changed.connect(self._update_cursor_status)
            editor.document().modificationChanged.connect(lambda m: self._update_tab_title(editor))
            idx = self.tabs.addTab(editor, file_path.name)
            self.tabs.setCurrentIndex(idx)
            self.file_opened.emit(file_path)
            return editor
        return None

    def open_file_dialog(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Script", "",
            "Python Scripts (*.py);;JSON Files (*.json);;All Files (*.*)"
        )
        if file_path:
            self.open_file(Path(file_path))

    def save_current_file(self) -> bool:
        editor = self.current_editor()
        if not editor:
            return False

        if editor.file_path:
            success = editor.save_file()
            if success:
                self._update_tab_title(editor)
                self.file_saved.emit(editor.file_path)
            return success
        else:
            return self.save_current_file_as()

    def save_current_file_as(self) -> bool:
        editor = self.current_editor()
        if not editor:
            return False

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Script As", "",
            "Python Scripts (*.py);;JSON Files (*.json);;All Files (*.*)"
        )
        if not file_path:
            return False

        path = Path(file_path)
        success = editor.save_file(path)
        if success:
            self._update_tab_title(editor)
            self.file_saved.emit(path)
        return success

    def close_tab(self, index: int) -> None:
        editor = self.tabs.widget(index)
        if isinstance(editor, CodeEditor) and editor.document().isModified():
            tab_name = self.tabs.tabText(index).rstrip(" *")
            ret = QMessageBox.warning(
                self, "Unsaved Changes",
                f"Save changes to '{tab_name}' before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            if ret == QMessageBox.StandardButton.Save:
                if not self.save_current_file():
                    return
            elif ret == QMessageBox.StandardButton.Cancel:
                return

        self.tabs.removeTab(index)

    def _on_tab_changed(self, index: int) -> None:
        editor = self.current_editor()
        if editor:
            self.find_replace_bar.set_editor(editor)
            cursor = editor.textCursor()
            self._update_cursor_status(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)
            self.lbl_total_lines.setText(f"{editor.blockCount()} lines")
            if editor.file_path:
                ext = editor.file_path.suffix.upper().lstrip(".")
                self.lbl_lang.setText(ext or "Python")
            else:
                self.lbl_lang.setText("Python")

    def _update_tab_title(self, editor: CodeEditor) -> None:
        idx = self.tabs.indexOf(editor)
        if idx >= 0:
            name = editor.file_path.name if editor.file_path else f"script_{idx+1}.py"
            if editor.document().isModified():
                name += " *"
            self.tabs.setTabText(idx, name)

    def _update_cursor_status(self, line: int, col: int) -> None:
        self.lbl_cursor_pos.setText(f"Ln {line}, Col {col}")
        editor = self.current_editor()
        if editor:
            self.lbl_total_lines.setText(f"{editor.blockCount()} lines")

    def toggle_find(self) -> None:
        editor = self.current_editor()
        if not editor:
            return
        selected = editor.textCursor().selectedText()
        self.find_replace_bar.set_editor(editor)
        self.find_replace_bar.show_find(selected)

    def toggle_replace(self) -> None:
        editor = self.current_editor()
        if not editor:
            return
        selected = editor.textCursor().selectedText()
        self.find_replace_bar.set_editor(editor)
        self.find_replace_bar.show_replace(selected)

    def run_current_script(self) -> None:
        editor = self.current_editor()
        if not editor:
            return
        code = editor.toPlainText()
        path = editor.file_path or Path("")
        self.run_script_requested.emit(code, path)
