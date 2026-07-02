from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit


class RuntimeConsolePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Runtime Console")
        title.setObjectName("PanelTitle")

        self.console = QTextEdit()
        self.console.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.console)

    def log(self, message: str) -> None:
        self.console.append(message)