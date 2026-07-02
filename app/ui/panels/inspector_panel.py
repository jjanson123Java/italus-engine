from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit


class InspectorPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Inspector")
        title.setObjectName("PanelTitle")

        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setText(
            "Runtime Status: Idle\n"
            "Guardian: —\n"
            "Tone: —\n"
            "Validation: —\n"
            "Continuity Impact: —"
        )

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.status)

    def set_status(self, text: str) -> None:
        self.status.setText(text)