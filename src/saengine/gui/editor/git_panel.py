"""
Git Version Control Panel for SAEngine Code Studio.

Provides an integrated Git GUI for repository management:
- Active branch detection, branch switcher, and branch creation
- Real-time status display of Staged, Unstaged, and Untracked files
- Staging / Unstaging / Discard actions
- Commit message composer with quick commit and commit & push
- Remote sync: Fetch, Pull, Push
- Interactive Syntax-Colored Diff viewer
- Repository commit history log viewer
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from PySide6.QtCore import Qt, Signal, QProcess, QByteArray
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QLineEdit, QComboBox, QTabWidget, QSplitter, QInputDialog,
    QMessageBox, QMenu, QHeaderView
)

from saengine.gui.editor.syntax_highlighter import DiffHighlighter


class GitService:
    """Helper for executing git operations synchronously or asynchronously."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir

    def is_git_repo(self) -> bool:
        return (self.repo_dir / ".git").exists()

    def run_git(self, args: List[str]) -> Tuple[int, str, str]:
        """Execute a git command and return (exit_code, stdout, stderr)."""
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return -1, "", str(e)

    def get_current_branch(self) -> str:
        code, out, _ = self.run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        return out.strip() if code == 0 else "unknown"

    def get_branches(self) -> List[str]:
        code, out, _ = self.run_git(["branch", "--format=%(refname:short)"])
        if code == 0:
            return [b.strip() for b in out.strip().splitlines() if b.strip()]
        return []

    def get_status(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        Parse git status --porcelain.
        Returns dict with keys: 'staged', 'unstaged', 'untracked'.
        Each value is a list of (status_code, filename).
        """
        res = {"staged": [], "unstaged": [], "untracked": []}
        code, out, _ = self.run_git(["status", "--porcelain"])
        if code != 0 or not out.strip():
            return res

        for line in out.splitlines():
            if len(line) < 3:
                continue
            x = line[0]  # index / staged status
            y = line[1]  # work tree / unstaged status
            filename = line[3:].strip()

            if x == "?" and y == "?":
                res["untracked"].append(("?", filename))
            else:
                if x in ("M", "A", "D", "R", "C"):
                    res["staged"].append((x, filename))
                if y in ("M", "D"):
                    res["unstaged"].append((y, filename))

        return res

    def get_diff(self, file_path: Optional[str] = None, cached: bool = False) -> str:
        args = ["diff"]
        if cached:
            args.append("--cached")
        if file_path:
            args.extend(["--", file_path])
        code, out, _ = self.run_git(args)
        return out if code == 0 else ""

    def get_log(self, max_count: int = 20) -> List[Dict[str, str]]:
        code, out, _ = self.run_git([
            "log", f"-n{max_count}",
            "--pretty=format:%h|%an|%ar|%s"
        ])
        commits = []
        if code == 0 and out.strip():
            for line in out.splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    commits.append({
                        "hash": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "subject": parts[3]
                    })
        return commits


class GitPanel(QWidget):
    """
    Complete Git source control panel.
    """

    status_updated = Signal(str)  # branch name
    file_selected_for_diff = Signal(str)

    def __init__(self, repo_dir: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.repo_dir = repo_dir or Path.cwd()
        self.git = GitService(self.repo_dir)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 1. Header: Branch selector & remote sync
        header_bar = QHBoxLayout()
        header_bar.setSpacing(4)

        lbl_git = QLabel("SOURCE CONTROL")
        lbl_git.setObjectName("panelHeader")
        lbl_git.setStyleSheet("font-weight: bold; color: #9aa0a6; padding: 2px;")
        header_bar.addWidget(lbl_git)

        header_bar.addStretch()

        btn_fetch = QToolButton(self)
        btn_fetch.setText("⬇ Fetch")
        btn_fetch.setToolTip("Fetch from remote")
        btn_fetch.clicked.connect(self.git_fetch)
        header_bar.addWidget(btn_fetch)

        btn_pull = QToolButton(self)
        btn_pull.setText("⤓ Pull")
        btn_pull.setToolTip("Pull latest changes")
        btn_pull.clicked.connect(self.git_pull)
        header_bar.addWidget(btn_pull)

        btn_push = QToolButton(self)
        btn_push.setText("⤒ Push")
        btn_push.setToolTip("Push committed changes")
        btn_push.clicked.connect(self.git_push)
        header_bar.addWidget(btn_push)

        btn_refresh = QToolButton(self)
        btn_refresh.setText("🔄")
        btn_refresh.setToolTip("Refresh Git Status")
        btn_refresh.clicked.connect(self.refresh)
        header_bar.addWidget(btn_refresh)

        layout.addLayout(header_bar)

        # 2. Branch Bar
        branch_bar = QHBoxLayout()
        branch_bar.setSpacing(4)

        lbl_branch_icon = QLabel("")
        lbl_branch_icon.setStyleSheet("color: #4FC3F7; font-size: 14px; font-weight: bold;")
        branch_bar.addWidget(lbl_branch_icon)

        self.combo_branch = QComboBox(self)
        self.combo_branch.setStyleSheet("""
            QComboBox {
                background-color: #1a1d23;
                border: 1px solid #2d313a;
                border-radius: 4px;
                color: #e8eaed;
                padding: 3px 8px;
                font-size: 11px;
            }
        """)
        self.combo_branch.activated.connect(self._on_branch_switched)
        branch_bar.addWidget(self.combo_branch, 1)

        btn_new_branch = QToolButton(self)
        btn_new_branch.setText("+")
        btn_new_branch.setToolTip("Create New Branch")
        btn_new_branch.clicked.connect(self.create_branch)
        branch_bar.addWidget(btn_new_branch)

        layout.addLayout(branch_bar)

        # 3. Main tabs: Changes | Diff | History
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #14161a;
            }
            QTabBar::tab {
                background-color: #1e2128;
                color: #9aa0a6;
                padding: 4px 10px;
                border: 1px solid #2d313a;
                border-bottom: none;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background-color: #14161a;
                color: #4FC3F7;
                font-weight: bold;
                border-top: 2px solid #4FC3F7;
            }
        """)

        # Tab 1: Changes & Commit
        tab_changes = QWidget()
        layout_changes = QVBoxLayout(tab_changes)
        layout_changes.setContentsMargins(2, 4, 2, 2)
        layout_changes.setSpacing(4)

        # Staging action buttons
        staging_actions = QHBoxLayout()
        staging_actions.setSpacing(4)

        btn_stage_all = QToolButton(self)
        btn_stage_all.setText("+ Stage All")
        btn_stage_all.setToolTip("Stage all modified & untracked files (git add -A)")
        btn_stage_all.clicked.connect(self.stage_all)
        staging_actions.addWidget(btn_stage_all)

        btn_unstage_all = QToolButton(self)
        btn_unstage_all.setText("- Unstage All")
        btn_unstage_all.setToolTip("Unstage all staged files (git reset)")
        btn_unstage_all.clicked.connect(self.unstage_all)
        staging_actions.addWidget(btn_unstage_all)

        staging_actions.addStretch()
        layout_changes.addLayout(staging_actions)

        # Tree of changes
        self.tree_changes = QTreeWidget(self)
        self.tree_changes.setHeaderHidden(True)
        self.tree_changes.setAnimated(True)
        self.tree_changes.setStyleSheet("""
            QTreeWidget {
                background-color: #14161a;
                color: #e8eaed;
                border: 1px solid #2d313a;
                border-radius: 4px;
                font-size: 12px;
            }
            QTreeWidget::item {
                padding: 3px 2px;
            }
            QTreeWidget::item:hover {
                background-color: #252830;
            }
            QTreeWidget::item:selected {
                background-color: #264f78;
            }
        """)
        self.tree_changes.itemClicked.connect(self._on_change_item_clicked)
        self.tree_changes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_changes.customContextMenuRequested.connect(self._show_change_context_menu)
        layout_changes.addWidget(self.tree_changes, 1)

        # Commit Box
        commit_box = QVBoxLayout()
        commit_box.setSpacing(4)

        self.edit_commit_msg = QTextEdit(self)
        self.edit_commit_msg.setFixedHeight(56)
        self.edit_commit_msg.setPlaceholderText("Commit message (Ctrl+Enter to commit)...")
        self.edit_commit_msg.setStyleSheet("""
            QTextEdit {
                background-color: #1a1d23;
                color: #e8eaed;
                border: 1px solid #2d313a;
                border-radius: 4px;
                font-size: 12px;
                padding: 4px;
            }
            QTextEdit:focus {
                border-color: #4FC3F7;
            }
        """)
        commit_box.addWidget(self.edit_commit_msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.btn_commit = QPushButton("✓ Commit")
        self.btn_commit.setStyleSheet("""
            QPushButton {
                background-color: #1b4d3e;
                color: #81C784;
                font-weight: bold;
                border: 1px solid #2e7d32;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #2e7d32;
                color: #ffffff;
            }
        """)
        self.btn_commit.clicked.connect(self.git_commit)
        btn_row.addWidget(self.btn_commit, 1)

        self.btn_commit_push = QPushButton("✓ & Push")
        self.btn_commit_push.setToolTip("Commit and push to remote")
        self.btn_commit_push.setStyleSheet("""
            QPushButton {
                background-color: #1a365d;
                color: #81D4FA;
                font-weight: bold;
                border: 1px solid #0288D1;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #0288D1;
                color: #ffffff;
            }
        """)
        self.btn_commit_push.clicked.connect(self.git_commit_and_push)
        btn_row.addWidget(self.btn_commit_push)

        commit_box.addLayout(btn_row)
        layout_changes.addLayout(commit_box)

        self.tabs.addTab(tab_changes, "Changes")

        # Tab 2: Diff Viewer
        tab_diff = QWidget()
        layout_diff = QVBoxLayout(tab_diff)
        layout_diff.setContentsMargins(2, 2, 2, 2)
        layout_diff.setSpacing(2)

        self.diff_viewer = QTextEdit(self)
        self.diff_viewer.setReadOnly(True)
        self.diff_viewer.setFont(QFont("Consolas", 11))
        self.diff_viewer.setStyleSheet("""
            QTextEdit {
                background-color: #101216;
                color: #e8eaed;
                border: 1px solid #2d313a;
                border-radius: 4px;
            }
        """)
        self.diff_highlighter = DiffHighlighter(self.diff_viewer.document())
        layout_diff.addWidget(self.diff_viewer)

        self.tabs.addTab(tab_diff, "Diff")

        # Tab 3: History / Log
        tab_history = QWidget()
        layout_history = QVBoxLayout(tab_history)
        layout_history.setContentsMargins(2, 2, 2, 2)
        layout_history.setSpacing(2)

        self.tree_history = QTreeWidget(self)
        self.tree_history.setHeaderLabels(["Commit", "Message", "Author", "Date"])
        self.tree_history.header().resizeSection(0, 70)
        self.tree_history.header().resizeSection(1, 200)
        self.tree_history.setStyleSheet("""
            QTreeWidget {
                background-color: #14161a;
                color: #e8eaed;
                border: 1px solid #2d313a;
                font-size: 11px;
            }
            QTreeWidget::item {
                padding: 3px 2px;
            }
            QTreeWidget::item:hover {
                background-color: #252830;
            }
        """)
        layout_history.addWidget(self.tree_history)

        self.tabs.addTab(tab_history, "History")

        layout.addWidget(self.tabs, 1)

    def set_repo_dir(self, path: Path) -> None:
        self.repo_dir = Path(path).resolve()
        self.git = GitService(self.repo_dir)
        self.refresh()

    def refresh(self) -> None:
        """Refresh branch list, changes tree, and history."""
        if not self.git.is_git_repo():
            self.tree_changes.clear()
            item = QTreeWidgetItem(self.tree_changes, ["Not a git repository."])
            return

        # 1. Update Branch Dropdown
        current = self.git.get_current_branch()
        self.status_updated.emit(current)

        branches = self.git.get_branches()
        self.combo_branch.blockSignals(True)
        self.combo_branch.clear()
        for b in branches:
            self.combo_branch.addItem(b)
        idx = self.combo_branch.findText(current)
        if idx >= 0:
            self.combo_branch.setCurrentIndex(idx)
        self.combo_branch.blockSignals(False)

        # 2. Update Changes
        status = self.git.get_status()
        self.tree_changes.clear()

        # Group: Staged Changes
        staged_items = status.get("staged", [])
        root_staged = QTreeWidgetItem(self.tree_changes, [f"Staged Changes ({len(staged_items)})"])
        root_staged.setExpanded(True)
        for stat, filename in staged_items:
            child = QTreeWidgetItem(root_staged, [f"[{stat}] {filename}"])
            child.setData(0, Qt.ItemDataRole.UserRole, ("staged", filename))
            child.setForeground(0, QColor("#81C784"))

        # Group: Changes (Unstaged)
        unstaged_items = status.get("unstaged", [])
        root_unstaged = QTreeWidgetItem(self.tree_changes, [f"Changes ({len(unstaged_items)})"])
        root_unstaged.setExpanded(True)
        for stat, filename in unstaged_items:
            child = QTreeWidgetItem(root_unstaged, [f"[{stat}] {filename}"])
            child.setData(0, Qt.ItemDataRole.UserRole, ("unstaged", filename))
            child.setForeground(0, QColor("#4FC3F7" if stat == "M" else "#E57373"))

        # Group: Untracked Files
        untracked_items = status.get("untracked", [])
        if untracked_items:
            root_untracked = QTreeWidgetItem(self.tree_changes, [f"Untracked Files ({len(untracked_items)})"])
            root_untracked.setExpanded(True)
            for stat, filename in untracked_items:
                child = QTreeWidgetItem(root_untracked, [f"[?] {filename}"])
                child.setData(0, Qt.ItemDataRole.UserRole, ("untracked", filename))
                child.setForeground(0, QColor("#9aa0a6"))

        # 3. Update History
        self.tree_history.clear()
        commits = self.git.get_log(30)
        for c in commits:
            item = QTreeWidgetItem(self.tree_history, [c["hash"], c["subject"], c["author"], c["date"]])
            item.setForeground(0, QColor("#FFCB6B"))

    def _on_change_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        group, filename = data
        diff = self.git.get_diff(filename, cached=(group == "staged"))
        if not diff and group == "untracked":
            # For untracked, show file contents as added
            try:
                full_path = self.repo_dir / filename
                if full_path.is_file():
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    diff = f"--- /dev/null\n+++ b/{filename}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + l for l in lines)
            except Exception:
                pass

        self.diff_viewer.setPlainText(diff or "(No diff to display)")
        self.file_selected_for_diff.emit(filename)

    def _show_change_context_menu(self, pos) -> None:
        item = self.tree_changes.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        group, filename = data

        menu = QMenu(self)
        if group == "staged":
            act = menu.addAction("Unstage File")
            act.triggered.connect(lambda: self.unstage_file(filename))
        else:
            act = menu.addAction("Stage File")
            act.triggered.connect(lambda: self.stage_file(filename))

            if group == "unstaged":
                act_discard = menu.addAction("Discard Changes")
                act_discard.triggered.connect(lambda: self.discard_file(filename))

        menu.exec(self.tree_changes.viewport().mapToGlobal(pos))

    # ── Git Operations ──────────────────────────────────────────

    def stage_file(self, filename: str) -> None:
        self.git.run_git(["add", "--", filename])
        self.refresh()

    def stage_all(self) -> None:
        self.git.run_git(["add", "-A"])
        self.refresh()

    def unstage_file(self, filename: str) -> None:
        self.git.run_git(["reset", "HEAD", "--", filename])
        self.refresh()

    def unstage_all(self) -> None:
        self.git.run_git(["reset", "HEAD"])
        self.refresh()

    def discard_file(self, filename: str) -> None:
        ret = QMessageBox.warning(
            self, "Discard Changes",
            f"Are you sure you want to discard changes in '{filename}'?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.git.run_git(["checkout", "--", filename])
            self.refresh()

    def git_commit(self) -> bool:
        msg = self.edit_commit_msg.toPlainText().strip()
        if not msg:
            QMessageBox.information(self, "Commit", "Please enter a commit message.")
            return False

        code, out, err = self.git.run_git(["commit", "-m", msg])
        if code == 0:
            self.edit_commit_msg.clear()
            self.refresh()
            return True
        else:
            QMessageBox.critical(self, "Commit Failed", err or out or "Unknown error")
            return False

    def git_commit_and_push(self) -> None:
        if self.git_commit():
            self.git_push()

    def git_push(self) -> None:
        code, out, err = self.git.run_git(["push"])
        if code == 0:
            QMessageBox.information(self, "Push", "Pushed successfully.")
            self.refresh()
        else:
            QMessageBox.warning(self, "Push Result", err or out or "Push finished")

    def git_pull(self) -> None:
        code, out, err = self.git.run_git(["pull"])
        if code == 0:
            QMessageBox.information(self, "Pull", out or "Already up to date.")
            self.refresh()
        else:
            QMessageBox.warning(self, "Pull Result", err or out or "Pull finished")

    def git_fetch(self) -> None:
        code, out, err = self.git.run_git(["fetch"])
        self.refresh()

    def _on_branch_switched(self, index: int) -> None:
        branch = self.combo_branch.itemText(index)
        code, out, err = self.git.run_git(["checkout", branch])
        if code != 0:
            QMessageBox.critical(self, "Branch Switch Failed", err or out)
        self.refresh()

    def create_branch(self) -> None:
        name, ok = QInputDialog.getText(self, "New Branch", "Enter new branch name:")
        if ok and name.strip():
            code, out, err = self.git.run_git(["checkout", "-b", name.strip()])
            if code == 0:
                self.refresh()
            else:
                QMessageBox.critical(self, "Failed to create branch", err or out)
