from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter

from app.ui.panels.navigator_panel import NavigatorPanel
from app.ui.panels.author_workspace_panel import AuthorWorkspacePanel
from app.ui.panels.inspector_panel import InspectorPanel
from app.ui.panels.runtime_console_panel import RuntimeConsolePanel


class WorkspacePage(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.navigator = NavigatorPanel()
        self.author_workspace = AuthorWorkspacePanel()
        self.inspector = InspectorPanel()
        self.console = RuntimeConsolePanel()

        horizontal = QSplitter(Qt.Horizontal)
        horizontal.addWidget(self.navigator)
        horizontal.addWidget(self.author_workspace)
        horizontal.addWidget(self.inspector)
        horizontal.setStretchFactor(0, 1)
        horizontal.setStretchFactor(1, 4)
        horizontal.setStretchFactor(2, 1)

        vertical = QSplitter(Qt.Vertical)
        vertical.addWidget(horizontal)
        vertical.addWidget(self.console)
        vertical.setStretchFactor(0, 5)
        vertical.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(vertical)

    def set_project_mode(self, mode: str) -> None:
        self.console.log(f"Workspace opened in mode: {mode}")
        self.inspector.set_status(f"Project mode: {mode}")