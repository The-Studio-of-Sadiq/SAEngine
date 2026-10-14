"""
Command manager implementing undo/redo via the Command pattern.

Every model-modifying action is wrapped in a Command object. This enables
full undo/redo support and maintains an audit trail of all changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from PySide6.QtCore import QObject, Signal


class Command(ABC):
    """Abstract base class for all undoable commands."""

    def __init__(self, description: str = ""):
        self.description = description

    @abstractmethod
    def execute(self) -> None:
        """Execute the command (do the action)."""
        ...

    @abstractmethod
    def undo(self) -> None:
        """Undo the command (reverse the action)."""
        ...

    def redo(self) -> None:
        """Redo the command. Default implementation re-executes."""
        self.execute()


class CompositeCommand(Command):
    """A command that groups multiple sub-commands into one undoable operation."""

    def __init__(self, description: str, commands: Optional[List[Command]] = None):
        super().__init__(description)
        self.commands: List[Command] = commands or []

    def add(self, command: Command) -> None:
        self.commands.append(command)

    def execute(self) -> None:
        for cmd in self.commands:
            cmd.execute()

    def undo(self) -> None:
        for cmd in reversed(self.commands):
            cmd.undo()


class CommandManager(QObject):
    """
    Manages the undo/redo stack.

    Emits signals when the stack changes so the GUI can update
    undo/redo button states and labels.
    """

    # Signals
    stack_changed = Signal()           # Emitted when undo/redo stack changes
    command_executed = Signal(str)      # Emitted with command description

    def __init__(self, max_undo: int = 200, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._undo_stack: List[Command] = []
        self._redo_stack: List[Command] = []
        self._max_undo = max_undo

    def execute(self, command: Command) -> None:
        """Execute a command and push it onto the undo stack."""
        command.execute()
        self._undo_stack.append(command)

        # Clear redo stack — any new action invalidates the redo history
        self._redo_stack.clear()

        # Limit stack size
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)

        self.stack_changed.emit()
        self.command_executed.emit(command.description)

    def undo(self) -> Optional[Command]:
        """Undo the most recent command."""
        if not self.can_undo:
            return None

        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)

        self.stack_changed.emit()
        return command

    def redo(self) -> Optional[Command]:
        """Redo the most recently undone command."""
        if not self.can_redo:
            return None

        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)

        self.stack_changed.emit()
        return command

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def undo_description(self) -> str:
        """Description of the next undo action."""
        if self._undo_stack:
            return f"Undo: {self._undo_stack[-1].description}"
        return "Nothing to undo"

    @property
    def redo_description(self) -> str:
        """Description of the next redo action."""
        if self._redo_stack:
            return f"Redo: {self._redo_stack[-1].description}"
        return "Nothing to redo"

    def clear(self) -> None:
        """Clear both undo and redo stacks."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.stack_changed.emit()
