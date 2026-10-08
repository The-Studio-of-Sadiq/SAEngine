"""
SAEngine Editor Module.

Provides VS Code web integration for the SAEngine desktop application.
The editor embeds a full VS Code instance via ``code serve-web`` inside
a QWebEngineView, giving users access to file explorer, git, terminal,
extensions, and the full VS Code editing experience.
"""

from saengine.gui.editor.vscode_server import VSCodeServerManager
from saengine.gui.editor.vscode_widget import VSCodeWebView

__all__ = ["VSCodeServerManager", "VSCodeWebView"]
