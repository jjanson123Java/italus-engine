from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QStackedWidget

from app.ui.shell.landing_page import LandingPage
from app.ui.shell.workspace_page import WorkspacePage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Narrative Studio")
        self.resize(1500, 900)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.landing_page = LandingPage()
        self.workspace_page = WorkspacePage()

        self.stack.addWidget(self.landing_page)
        self.stack.addWidget(self.workspace_page)

        self._build_menu()

        self.landing_page.new_project_requested.connect(self.open_workspace)
        self.landing_page.existing_project_requested.connect(self.open_workspace)
        self.landing_page.archived_project_requested.connect(self.open_workspace)

    def _build_menu(self) -> None:
        menu = self.menuBar()

        menu.addMenu("File")
        menu.addMenu("Project")
        menu.addMenu("Engine")
        menu.addMenu("Generate")
        menu.addMenu("Validation")
        menu.addMenu("Templates")
        menu.addMenu("View")
        menu.addMenu("Settings")
        menu.addMenu("Help")

    def open_workspace(self, project_mode: str) -> None:
        self.workspace_page.set_project_mode(project_mode)
        self.stack.setCurrentWidget(self.workspace_page)