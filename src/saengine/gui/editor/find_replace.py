"""
Find and Replace bar for SAEngine Code Studio.

Integrated search & replace bar with case sensitivity, whole word,
regular expression options, and real-time match counters.
"""

from __future__ import annotations

from typing import Optional
from PySide6.QtCore import Qt, Signal, QRegularExpression
from PySide6.QtGui import QTextCursor, QTextDocument, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel, QToolButton, QPlainTextEdit, QSizePolicy
)


class FindReplaceBar(QWidget):
    """
    Search and replace toolbar that attaches directly to a CodeEditor widget.
    """

    find_closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._editor: Optional[QPlainTextEdit] = None

        self.setObjectName("findReplaceBar")
        self.setStyleSheet("""
            QWidget#findReplaceBar {
                background-color: #252830;
                border: 1px solid #353840;
                border-radius: 6px;
                padding: 4px;
            }
            QLineEdit {
                background-color: #1a1d23;
                border: 1px solid #353840;
                border-radius: 4px;
                color: #e8eaed;
                padding: 4px 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #4FC3F7;
            }
            QPushButton, QToolButton {
                background-color: #2d313a;
                border: 1px solid #353840;
                border-radius: 4px;
                color: #e8eaed;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: #353840;
                border-color: #4FC3F7;
            }
            QPushButton:pressed, QToolButton:pressed {
                background-color: #4FC3F7;
                color: #1a1d23;
            }
            QCheckBox {
                color: #9aa0a6;
                font-size: 11px;
            }
            QCheckBox:hover {
                color: #e8eaed;
            }
            QLabel {
                color: #9aa0a6;
                font-size: 11px;
            }
        """)

        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # Row 1: Find
        row_find = QHBoxLayout()
        row_find.setSpacing(6)

        lbl_find = QLabel("Find:")
        lbl_find.setFixedWidth(45)
        row_find.addWidget(lbl_find)

        self.edit_find = QLineEdit()
        self.edit_find.setPlaceholderText("Search text...")
        self.edit_find.textChanged.connect(self._on_search_text_changed)
        self.edit_find.returnPressed.connect(self.find_next)
        row_find.addWidget(self.edit_find, 1)

        self.btn_prev = QToolButton()
        self.btn_prev.setText("▲")
        self.btn_prev.setToolTip("Previous Match (Shift+Enter)")
        self.btn_prev.clicked.connect(self.find_prev)
        row_find.addWidget(self.btn_prev)

        self.btn_next = QToolButton()
        self.btn_next.setText("▼")
        self.btn_next.setToolTip("Next Match (Enter)")
        self.btn_next.clicked.connect(self.find_next)
        row_find.addWidget(self.btn_next)

        self.lbl_matches = QLabel("0 matches")
        self.lbl_matches.setMinimumWidth(80)
        row_find.addWidget(self.lbl_matches)

        self.chk_case = QCheckBox("Aa")
        self.chk_case.setToolTip("Match Case")
        self.chk_case.toggled.connect(self._on_search_text_changed)
        row_find.addWidget(self.chk_case)

        self.chk_word = QCheckBox(r"\b")
        self.chk_word.setToolTip("Match Whole Word")
        self.chk_word.toggled.connect(self._on_search_text_changed)
        row_find.addWidget(self.chk_word)

        self.chk_regex = QCheckBox(".*")
        self.chk_regex.setToolTip("Use Regular Expression")
        self.chk_regex.toggled.connect(self._on_search_text_changed)
        row_find.addWidget(self.chk_regex)

        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("Close (Esc)")
        self.btn_close.clicked.connect(self.close_bar)
        row_find.addWidget(self.btn_close)

        main_layout.addLayout(row_find)

        # Row 2: Replace
        self.row_replace = QHBoxLayout()
        self.row_replace.setSpacing(6)

        lbl_replace = QLabel("Replace:")
        lbl_replace.setFixedWidth(45)
        self.row_replace.addWidget(lbl_replace)

        self.edit_replace = QLineEdit()
        self.edit_replace.setPlaceholderText("Replace with...")
        self.edit_replace.returnPressed.connect(self.replace)
        self.row_replace.addWidget(self.edit_replace, 1)

        self.btn_replace = QPushButton("Replace")
        self.btn_replace.setToolTip("Replace Current Match")
        self.btn_replace.clicked.connect(self.replace)
        self.row_replace.addWidget(self.btn_replace)

        self.btn_replace_all = QPushButton("Replace All")
        self.btn_replace_all.setToolTip("Replace All Occurrences")
        self.btn_replace_all.clicked.connect(self.replace_all)
        self.row_replace.addWidget(self.btn_replace_all)

        main_layout.addLayout(self.row_replace)

    def set_editor(self, editor: Optional[QPlainTextEdit]) -> None:
        """Set the target code editor."""
        self._editor = editor

    def show_find(self, initial_text: str = "") -> None:
        """Open the bar in Find mode."""
        self.row_replace.setEnabled(False)
        self.edit_replace.setVisible(False)
        self.btn_replace.setVisible(False)
        self.btn_replace_all.setVisible(False)
        self.show()
        if initial_text:
            self.edit_find.setText(initial_text)
            self.edit_find.selectAll()
        self.edit_find.setFocus()
        self._update_match_count()

    def show_replace(self, initial_text: str = "") -> None:
        """Open the bar in Replace mode."""
        self.row_replace.setEnabled(True)
        self.edit_replace.setVisible(True)
        self.btn_replace.setVisible(True)
        self.btn_replace_all.setVisible(True)
        self.show()
        if initial_text:
            self.edit_find.setText(initial_text)
            self.edit_find.selectAll()
        self.edit_find.setFocus()
        self._update_match_count()

    def close_bar(self) -> None:
        """Close find bar and refocus editor."""
        self.hide()
        if self._editor:
            self._editor.setFocus()
        self.find_closed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
        else:
            super().keyPressEvent(event)

    def _get_flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self.chk_case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.chk_word.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def _on_search_text_changed(self) -> None:
        self._update_match_count()

    def _update_match_count(self) -> None:
        if not self._editor or not self.edit_find.text():
            self.lbl_matches.setText("0 matches")
            return

        query = self.edit_find.text()
        doc = self._editor.document()

        count = 0
        cursor = QTextCursor(doc)
        flags = self._get_flags()

        if self.chk_regex.isChecked():
            rx_options = QRegularExpression.PatternOption.NoPatternOption
            if not self.chk_case.isChecked():
                rx_options |= QRegularExpression.PatternOption.CaseInsensitiveOption
            rx = QRegularExpression(query, rx_options)
            cursor = doc.find(rx, cursor)
            while not cursor.isNull():
                count += 1
                cursor = doc.find(rx, cursor)
        else:
            cursor = doc.find(query, cursor, flags)
            while not cursor.isNull():
                count += 1
                cursor = doc.find(query, cursor, flags)

        self.lbl_matches.setText(f"{count} match{'es' if count != 1 else ''}")

    def find_next(self) -> bool:
        """Find next occurrence."""
        if not self._editor or not self.edit_find.text():
            return False

        query = self.edit_find.text()
        doc = self._editor.document()
        cursor = self._editor.textCursor()
        flags = self._get_flags()

        found = False
        if self.chk_regex.isChecked():
            rx_options = QRegularExpression.PatternOption.NoPatternOption
            if not self.chk_case.isChecked():
                rx_options |= QRegularExpression.PatternOption.CaseInsensitiveOption
            rx = QRegularExpression(query, rx_options)
            match_cursor = doc.find(rx, cursor)
            if match_cursor.isNull():
                # Wrap around from beginning
                match_cursor = doc.find(rx, QTextCursor(doc))
        else:
            match_cursor = doc.find(query, cursor, flags)
            if match_cursor.isNull():
                # Wrap around
                match_cursor = doc.find(query, QTextCursor(doc), flags)

        if not match_cursor.isNull():
            self._editor.setTextCursor(match_cursor)
            found = True

        self._update_match_count()
        return found

    def find_prev(self) -> bool:
        """Find previous occurrence."""
        if not self._editor or not self.edit_find.text():
            return False

        query = self.edit_find.text()
        doc = self._editor.document()
        cursor = self._editor.textCursor()
        flags = self._get_flags() | QTextDocument.FindFlag.FindBackward

        found = False
        if self.chk_regex.isChecked():
            rx_options = QRegularExpression.PatternOption.NoPatternOption
            if not self.chk_case.isChecked():
                rx_options |= QRegularExpression.PatternOption.CaseInsensitiveOption
            rx = QRegularExpression(query, rx_options)
            match_cursor = doc.find(rx, cursor, flags)
            if match_cursor.isNull():
                # Wrap around from end
                end_cursor = QTextCursor(doc)
                end_cursor.movePosition(QTextCursor.MoveOperation.End)
                match_cursor = doc.find(rx, end_cursor, flags)
        else:
            match_cursor = doc.find(query, cursor, flags)
            if match_cursor.isNull():
                end_cursor = QTextCursor(doc)
                end_cursor.movePosition(QTextCursor.MoveOperation.End)
                match_cursor = doc.find(query, end_cursor, flags)

        if not match_cursor.isNull():
            self._editor.setTextCursor(match_cursor)
            found = True

        self._update_match_count()
        return found

    def replace(self) -> None:
        """Replace current match and advance to next."""
        if not self._editor:
            return

        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(self.edit_replace.text())
        self.find_next()

    def replace_all(self) -> None:
        """Replace all occurrences in document."""
        if not self._editor or not self.edit_find.text():
            return

        query = self.edit_find.text()
        replacement = self.edit_replace.text()
        doc = self._editor.document()
        flags = self._get_flags()

        cursor = QTextCursor(doc)
        count = 0

        cursor.beginEditBlock()
        if self.chk_regex.isChecked():
            rx_options = QRegularExpression.PatternOption.NoPatternOption
            if not self.chk_case.isChecked():
                rx_options |= QRegularExpression.PatternOption.CaseInsensitiveOption
            rx = QRegularExpression(query, rx_options)
            match_cursor = doc.find(rx, cursor)
            while not match_cursor.isNull():
                match_cursor.insertText(replacement)
                count += 1
                match_cursor = doc.find(rx, match_cursor)
        else:
            match_cursor = doc.find(query, cursor, flags)
            while not match_cursor.isNull():
                match_cursor.insertText(replacement)
                count += 1
                match_cursor = doc.find(query, match_cursor, flags)
        cursor.endEditBlock()

        self.lbl_matches.setText(f"Replaced {count} occurrences")
