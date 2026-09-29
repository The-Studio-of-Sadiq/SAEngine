"""
Syntax highlighters for SAEngine Code Studio.

Provides syntax highlighting for Python (with OpenSeesPy & SAEngine structural
engineering extensions), JSON, Git Diffs, Markdown, and configuration files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextDocument
)


class BaseHighlighter(QSyntaxHighlighter):
    """Base class providing helper methods for styling text formats."""

    def __init__(self, parent: Optional[QTextDocument] = None):
        super().__init__(parent)
        self.rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []

    def _format(self, color_hex: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color_hex))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def highlightBlock(self, text: str) -> None:
        """Apply rules to the given text block."""
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class PythonHighlighter(BaseHighlighter):
    """
    Syntax highlighter for Python with specific enhancements for:
    - Standard Python syntax (keywords, strings, numbers, built-ins, comments)
    - OpenSeesPy finite-element commands (model, node, element, pattern, etc.)
    - SAEngine structural API classes and modules
    """

    def __init__(self, parent: Optional[QTextDocument] = None):
        super().__init__(parent)

        # Formats
        keyword_fmt = self._format("#C792EA", bold=True)       # Purple
        opensees_fmt = self._format("#4FC3F7", bold=True)      # Cyan / Primary
        builtin_fmt = self._format("#FFCB6B")                  # Amber
        def_fmt = self._format("#82AAFF", bold=True)          # Light Blue
        class_fmt = self._format("#4EC9B0", bold=True)        # Teal
        decorator_fmt = self._format("#FF5370", italic=True)  # Pink/Coral
        number_fmt = self._format("#F78C6C")                   # Orange
        comment_fmt = self._format("#676E95", italic=True)    # Muted Gray-Blue
        string_fmt = self._format("#C3E88D")                   # Soft Green
        self.docstring_fmt = self._format("#91B859", italic=True) # Darker green

        # 1. Python Standard Keywords
        python_keywords = [
            "and", "as", "assert", "break", "class", "continue", "def",
            "del", "elif", "else", "except", "finally", "for", "from",
            "global", "if", "import", "in", "is", "lambda", "nonlocal",
            "not", "or", "pass", "raise", "return", "try", "while",
            "with", "yield", "async", "await"
        ]
        for kw in python_keywords:
            pattern = QRegularExpression(rf"\b{kw}\b")
            self.rules.append((pattern, keyword_fmt))

        # 2. Builtins & Common Literals
        builtins = [
            "self", "cls", "True", "False", "None", "print", "len", "range",
            "enumerate", "zip", "dict", "list", "set", "str", "int", "float",
            "bool", "tuple", "super", "open", "isinstance", "type", "sum",
            "min", "max", "abs", "round", "any", "all", "dir", "getattr"
        ]
        for bi in builtins:
            pattern = QRegularExpression(rf"\b{bi}\b")
            self.rules.append((pattern, builtin_fmt))

        # 3. OpenSeesPy & SAEngine Structural Keywords
        structural_keywords = [
            # OpenSees commands
            "model", "node", "element", "pattern", "analysis", "analyze",
            "wipe", "wipeAnalysis", "uniaxialMaterial", "nDMaterial", "section",
            "geomTransf", "beamIntegration", "load", "sp", "fix", "fixX", "fixY", "fixZ",
            "equalDOF", "rigidDiaphragm", "mass", "rayleigh", "eigen",
            "system", "constraints", "numberer", "test", "algorithm",
            "integrator", "recorder", "reactions", "nodeDisp", "nodeVel",
            "nodeAccel", "nodeReaction", "eleResponse", "getTime", "setNodeCoord",
            # SAEngine API
            "Project", "GridSystem", "StorySystem", "GridLine", "StoryLevel",
            "Material", "Section", "Beam", "Column", "Wall", "Slab",
            "LoadCase", "LoadCombo", "Units", "CommandManager"
        ]
        for skw in structural_keywords:
            pattern = QRegularExpression(rf"\b{skw}\b")
            self.rules.append((pattern, opensees_fmt))

        # 4. Function & Class Declarations
        self.rules.append((QRegularExpression(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)"), def_fmt))
        self.rules.append((QRegularExpression(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"), class_fmt))

        # 5. Decorators
        self.rules.append((QRegularExpression(r"@[A-Za-z_][A-Za-z0-9_]*"), decorator_fmt))

        # 6. Numbers (integers, floats, scientific notation)
        self.rules.append((QRegularExpression(r"\b[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?\b"), number_fmt))

        # 7. Single-line Strings
        self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))
        self.rules.append((QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"), string_fmt))

        # 8. Comments (must be after strings so # inside strings isn't matched)
        self.rules.append((QRegularExpression(r"#.*$"), comment_fmt))

        # Multi-line docstring patterns
        self.triple_double = QRegularExpression(r'"""')
        self.triple_single = QRegularExpression(r"'''")

    def highlightBlock(self, text: str) -> None:
        super().highlightBlock(text)
        self._highlight_multiline_strings(text)

    def _highlight_multiline_strings(self, text: str) -> None:
        """Handle triple-quoted strings spanning multiple lines."""
        self.setCurrentBlockState(0)

        # States: 1 = inside """, 2 = inside '''
        start_idx = 0
        state = self.previousBlockState()

        if state == 1:
            match = self.triple_double.match(text)
            if not match.hasMatch():
                self.setFormat(0, len(text), self.docstring_fmt)
                self.setCurrentBlockState(1)
                return
            else:
                length = match.capturedEnd()
                self.setFormat(0, length, self.docstring_fmt)
                start_idx = match.capturedEnd()
                state = 0
        elif state == 2:
            match = self.triple_single.match(text)
            if not match.hasMatch():
                self.setFormat(0, len(text), self.docstring_fmt)
                self.setCurrentBlockState(2)
                return
            else:
                length = match.capturedEnd()
                self.setFormat(0, length, self.docstring_fmt)
                start_idx = match.capturedEnd()
                state = 0

        while start_idx < len(text):
            match_d = self.triple_double.match(text, start_idx)
            match_s = self.triple_single.match(text, start_idx)

            d_idx = match_d.capturedStart() if match_d.hasMatch() else -1
            s_idx = match_s.capturedStart() if match_s.hasMatch() else -1

            if d_idx == -1 and s_idx == -1:
                break

            if d_idx != -1 and (s_idx == -1 or d_idx < s_idx):
                end_match = self.triple_double.match(text, match_d.capturedEnd())
                if end_match.hasMatch():
                    length = end_match.capturedEnd() - match_d.capturedStart()
                    self.setFormat(match_d.capturedStart(), length, self.docstring_fmt)
                    start_idx = end_match.capturedEnd()
                else:
                    self.setFormat(match_d.capturedStart(), len(text) - match_d.capturedStart(), self.docstring_fmt)
                    self.setCurrentBlockState(1)
                    break
            else:
                end_match = self.triple_single.match(text, match_s.capturedEnd())
                if end_match.hasMatch():
                    length = end_match.capturedEnd() - match_s.capturedStart()
                    self.setFormat(match_s.capturedStart(), length, self.docstring_fmt)
                    start_idx = end_match.capturedEnd()
                else:
                    self.setFormat(match_s.capturedStart(), len(text) - match_s.capturedStart(), self.docstring_fmt)
                    self.setCurrentBlockState(2)
                    break


class JsonHighlighter(BaseHighlighter):
    """Syntax highlighter for JSON and configuration files."""

    def __init__(self, parent: Optional[QTextDocument] = None):
        super().__init__(parent)

        key_fmt = self._format("#9CDCFE")      # Light Blue keys
        string_fmt = self._format("#CE9178")   # Orange string values
        number_fmt = self._format("#B5CEA8")   # Light Green numbers
        bool_fmt = self._format("#569CD6", bold=True) # Keyword blue

        # Keys: "key":
        self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"\s*:'), key_fmt))
        # String values
        self.rules.append((QRegularExpression(r':\s*"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))
        # Standalone strings in lists
        self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))
        # Numbers
        self.rules.append((QRegularExpression(r'\b-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?\b'), number_fmt))
        # Booleans and null
        self.rules.append((QRegularExpression(r'\b(true|false|null)\b'), bool_fmt))


class DiffHighlighter(BaseHighlighter):
    """Syntax highlighter for Git unified diff output."""

    def __init__(self, parent: Optional[QTextDocument] = None):
        super().__init__(parent)

        self.added_fmt = QTextCharFormat()
        self.added_fmt.setForeground(QColor("#81C784"))  # Light green
        self.added_fmt.setBackground(QColor("#162e20"))

        self.deleted_fmt = QTextCharFormat()
        self.deleted_fmt.setForeground(QColor("#E57373"))  # Soft red
        self.deleted_fmt.setBackground(QColor("#381719"))

        self.header_fmt = self._format("#4FC3F7", bold=True)  # Blue
        self.hunk_fmt = self._format("#BA68C8", bold=True)    # Purple @@ ... @@

    def highlightBlock(self, text: str) -> None:
        if not text:
            return

        if text.startswith("+++") or text.startswith("---") or text.startswith("diff "):
            self.setFormat(0, len(text), self.header_fmt)
        elif text.startswith("@@"):
            self.setFormat(0, len(text), self.hunk_fmt)
        elif text.startswith("+"):
            self.setFormat(0, len(text), self.added_fmt)
        elif text.startswith("-"):
            self.setFormat(0, len(text), self.deleted_fmt)


class MarkdownHighlighter(BaseHighlighter):
    """Syntax highlighter for Markdown files."""

    def __init__(self, parent: Optional[QTextDocument] = None):
        super().__init__(parent)

        h1_fmt = self._format("#4FC3F7", bold=True)
        h2_fmt = self._format("#81D4FA", bold=True)
        h3_fmt = self._format("#B3E5FC", bold=True)
        bold_fmt = self._format("#FFFFFF", bold=True)
        italic_fmt = self._format("#B0BEC5", italic=True)
        code_fmt = self._format("#FFCB6B")
        link_fmt = self._format("#80CBC4")

        self.rules.append((QRegularExpression(r"^#\s.*$"), h1_fmt))
        self.rules.append((QRegularExpression(r"^##\s.*$"), h2_fmt))
        self.rules.append((QRegularExpression(r"^###+\s.*$"), h3_fmt))
        self.rules.append((QRegularExpression(r"\*\*[^*]+\*\*"), bold_fmt))
        self.rules.append((QRegularExpression(r"\*[^*]+\*"), italic_fmt))
        self.rules.append((QRegularExpression(r"`[^`]+`"), code_fmt))
        self.rules.append((QRegularExpression(r"\[.+?\]\(.+?\)"), link_fmt))


def get_highlighter_for_file(filepath: Optional[str | Path],
                             document: QTextDocument) -> Optional[BaseHighlighter]:
    """Factory creating the appropriate syntax highlighter based on file extension."""
    if not filepath:
        return PythonHighlighter(document)

    ext = Path(filepath).suffix.lower()
    if ext in [".py", ".pyw", ".tcl"]:
        return PythonHighlighter(document)
    elif ext in [".json", ".geojson", ".saengine"]:
        return JsonHighlighter(document)
    elif ext in [".diff", ".patch"]:
        return DiffHighlighter(document)
    elif ext in [".md", ".markdown"]:
        return MarkdownHighlighter(document)
    else:
        # Default to Python highlighter for scripts / unknown files
        return PythonHighlighter(document)
