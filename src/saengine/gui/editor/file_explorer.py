"""
File Explorer panel for SAEngine Code Studio.

Provides an interactive filesystem tree view for browsing project files,
managing scripts, creating/renaming/deleting files and folders, and opening
them directly in the code editor or terminal.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import Qt, Signal, QModelIndex, QSortFilterProxyModel, QDir
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QLineEdit,
    QToolButton, QLabel, QMenu, QInputDialog, QMessageBox,
    QFileDialog, QHeaderView, QFileSystemModel
)


class FileFilterProxyModel(QSortFilterProxyModel):
    """Filter out noisy virtual environment and cache folders from the tree view."""

    EXCLUDED_NAMES = {
        ".git", "__pycache__", ".pytest_cache", ".venv", "venv",
        "node_modules", ".idea", ".vscode", "build", "dist",
        "saengine.egg-info"
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.show_hidden = False
        self.filter_text = ""

    def set_show_hidden(self, show: bool) -> None:
        self.show_hidden = show
        self.invalidateFilter()

    def set_filter_text(self, text: str) -> None:
        self.filter_text = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source_model = self.sourceModel()
        if not isinstance(source_model, QFileSystemModel):
            return True

        index = source_model.index(source_row, 0, source_parent)
        filename = source_model.fileName(index)

        # Check exclusion
        if not self.show_hidden:
            if filename in self.EXCLUDED_NAMES or (filename.startswith(".") and filename != ".gitignore"):
                return False

        # Check search text filter
        if self.filter_text:
            # If directory, accept if any child matches or directory name matches
            if source_model.isDir(index):
                if self.filter_text in filename.lower():
                    return True
                # Check children
                child_count = source_model.rowCount(index)
                for i in range(child_count):
                    if self.filterAcceptsRow(i, index):
                        return True
                return False
            else:
                return self.filter_text in filename.lower()

        return True


class FileExplorerPanel(QWidget):
    """
    Dockable file explorer tree view for the workspace.
    """

    file_double_clicked = Signal(Path)
    open_in_terminal_requested = Signal(Path)

    def __init__(self, root_path: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.root_path = root_path or Path.cwd()

        self._build_ui()
        self.set_root_path(self.root_path)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 1. Header with folder title and actions
        header_bar = QHBoxLayout()
        header_bar.setSpacing(4)

        self.lbl_workspace = QLabel("WORKSPACE")
        self.lbl_workspace.setObjectName("panelHeader")
        self.lbl_workspace.setStyleSheet("font-weight: bold; color: #9aa0a6; padding: 2px;")
        header_bar.addWidget(self.lbl_workspace, 1)

        # Open Folder button
        btn_open_folder = QToolButton(self)
        btn_open_folder.setText("📁")
        btn_open_folder.setToolTip("Open Folder...")
        btn_open_folder.clicked.connect(self.choose_workspace_folder)
        header_bar.addWidget(btn_open_folder)

        # New File
        btn_new_file = QToolButton(self)
        btn_new_file.setText("📄+")
        btn_new_file.setToolTip("New File")
        btn_new_file.clicked.connect(self.create_new_file)
        header_bar.addWidget(btn_new_file)

        # New Folder
        btn_new_folder = QToolButton(self)
        btn_new_folder.setText("📁+")
        btn_new_folder.setToolTip("New Folder")
        btn_new_folder.clicked.connect(self.create_new_folder)
        header_bar.addWidget(btn_new_folder)

        # Refresh
        btn_refresh = QToolButton(self)
        btn_refresh.setText("🔄")
        btn_refresh.setToolTip("Refresh Explorer")
        btn_refresh.clicked.connect(self.refresh)
        header_bar.addWidget(btn_refresh)

        # Collapse
        btn_collapse = QToolButton(self)
        btn_collapse.setText("⊟")
        btn_collapse.setToolTip("Collapse All")
        btn_collapse.clicked.connect(self.tree.collapseAll if hasattr(self, 'tree') else lambda: None)
        header_bar.addWidget(btn_collapse)

        layout.addLayout(header_bar)

        # 2. Search / filter input
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Filter files (e.g. *.py)...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1d23;
                border: 1px solid #2d313a;
                border-radius: 4px;
                color: #e8eaed;
                padding: 3px 6px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #4FC3F7;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        # 3. File System Model & Proxy
        self.fs_model = QFileSystemModel()
        self.fs_model.setReadOnly(False)
        self.fs_model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)

        self.proxy_model = FileFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.fs_model)

        # 4. Tree View
        self.tree = QTreeView(self)
        self.tree.setModel(self.proxy_model)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # Hide size, type, date columns - keep only filename for clean sidebar
        self.tree.hideColumn(1)
        self.tree.hideColumn(2)
        self.tree.hideColumn(3)

        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.doubleClicked.connect(self._on_item_double_clicked)

        self.tree.setStyleSheet("""
            QTreeView {
                background-color: #14161a;
                color: #e8eaed;
                border: 1px solid #2d313a;
                border-radius: 4px;
                font-size: 12px;
                padding: 2px;
            }
            QTreeView::item {
                padding: 4px 2px;
                border-radius: 3px;
            }
            QTreeView::item:hover {
                background-color: #252830;
            }
            QTreeView::item:selected {
                background-color: #264f78;
                color: #ffffff;
            }
        """)

        layout.addWidget(self.tree, 1)

    def set_root_path(self, path: Path) -> None:
        """Set the active workspace directory."""
        self.root_path = Path(path).resolve()
        self.lbl_workspace.setText(f"📁 {self.root_path.name.upper()}")
        self.lbl_workspace.setToolTip(str(self.root_path))

        source_idx = self.fs_model.setRootPath(str(self.root_path))
        proxy_idx = self.proxy_model.mapFromSource(source_idx)
        self.tree.setRootIndex(proxy_idx)

    def choose_workspace_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace Folder", str(self.root_path))
        if folder:
            self.set_root_path(Path(folder))

    def refresh(self) -> None:
        self.fs_model.setRootPath(str(self.root_path))
        self.proxy_model.invalidate()

    def _on_search_changed(self, text: str) -> None:
        self.proxy_model.set_filter_text(text)
        if text:
            self.tree.expandAll()

    def _selected_path(self) -> Path:
        indexes = self.tree.selectedIndexes()
        if indexes:
            proxy_idx = indexes[0]
            source_idx = self.proxy_model.mapToSource(proxy_idx)
            return Path(self.fs_model.filePath(source_idx))
        return self.root_path

    def _on_item_double_clicked(self, proxy_idx: QModelIndex) -> None:
        source_idx = self.proxy_model.mapToSource(proxy_idx)
        file_path = Path(self.fs_model.filePath(source_idx))
        if file_path.is_file():
            self.file_double_clicked.emit(file_path)

    def _show_context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        target_path = self._selected_path() if index.isValid() else self.root_path

        menu = QMenu(self)

        if target_path.is_file():
            act_open = menu.addAction("Open in Code Editor")
            act_open.triggered.connect(lambda: self.file_double_clicked.emit(target_path))
            menu.addSeparator()

        act_terminal = menu.addAction("Open in Terminal")
        dir_to_open = target_path if target_path.is_dir() else target_path.parent
        act_terminal.triggered.connect(lambda: self.open_in_terminal_requested.emit(dir_to_open))

        act_reveal = menu.addAction("Reveal in File Explorer")
        act_reveal.triggered.connect(lambda: self._reveal_in_os(target_path))

        menu.addSeparator()

        act_new_file = menu.addAction("New File...")
        act_new_file.triggered.connect(lambda: self.create_new_file(dir_to_open))

        act_new_folder = menu.addAction("New Folder...")
        act_new_folder.triggered.connect(lambda: self.create_new_folder(dir_to_open))

        if index.isValid() and target_path != self.root_path:
            menu.addSeparator()
            act_rename = menu.addAction("Rename...")
            act_rename.triggered.connect(lambda: self.rename_item(target_path))

            act_delete = menu.addAction("Delete")
            act_delete.triggered.connect(lambda: self.delete_item(target_path))

        menu.addSeparator()
        act_copy_path = menu.addAction("Copy Full Path")
        act_copy_path.triggered.connect(lambda: self._copy_to_clipboard(str(target_path)))

        act_copy_rel = menu.addAction("Copy Relative Path")
        try:
            rel = target_path.relative_to(self.root_path)
            act_copy_rel.triggered.connect(lambda: self._copy_to_clipboard(str(rel)))
        except ValueError:
            pass

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def create_new_file(self, parent_dir: Optional[Path] = None) -> None:
        target_dir = parent_dir or (self._selected_path() if self._selected_path().is_dir() else self._selected_path().parent)
        name, ok = QInputDialog.getText(self, "New File", "Enter file name (e.g. script.py):")
        if ok and name.strip():
            file_path = target_dir / name.strip()
            try:
                file_path.touch(exist_ok=False)
                self.refresh()
                self.file_double_clicked.emit(file_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create file: {e}")

    def create_new_folder(self, parent_dir: Optional[Path] = None) -> None:
        target_dir = parent_dir or (self._selected_path() if self._selected_path().is_dir() else self._selected_path().parent)
        name, ok = QInputDialog.getText(self, "New Folder", "Enter folder name:")
        if ok and name.strip():
            folder_path = target_dir / name.strip()
            try:
                folder_path.mkdir(parents=True, exist_ok=False)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create folder: {e}")

    def rename_item(self, path: Path) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename", f"Rename '{path.name}' to:", text=path.name)
        if ok and new_name.strip() and new_name.strip() != path.name:
            target = path.parent / new_name.strip()
            try:
                path.rename(target)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not rename: {e}")

    def delete_item(self, path: Path) -> None:
        ret = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete '{path.name}'?\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret == QMessageBox.StandardButton.Yes:
            try:
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                else:
                    path.unlink()
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not delete: {e}")

    def _reveal_in_os(self, path: Path) -> None:
        """Reveal path in Windows Explorer or native file manager."""
        try:
            if sys.platform == "win32":
                if path.is_file():
                    subprocess.run(["explorer", "/select,", str(path)])
                else:
                    subprocess.run(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)])
            else:
                subprocess.run(["xdg-open", str(path.parent)])
        except Exception:
            pass

    def _copy_to_clipboard(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb:
            cb.setText(text)
