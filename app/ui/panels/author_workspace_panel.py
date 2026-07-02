from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget, QTextEdit


class AuthorWorkspacePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Author Workspace")
        title.setObjectName("PanelTitle")

        tabs = QTabWidget()

        self.prompt_preview = QTextEdit()
        self.prompt_preview.setPlaceholderText("Prompt preview will appear here.")

        self.canon_packet = QTextEdit()
        self.canon_packet.setPlaceholderText("Canon packet preview will appear here.")

        self.generated_chapter = QTextEdit()
        self.generated_chapter.setPlaceholderText("Generated chapter output will appear here.")

        self.revision = QTextEdit()
        self.revision.setPlaceholderText("Revision and refinement notes will appear here.")

        tabs.addTab(self.prompt_preview, "Prompt Preview")
        tabs.addTab(self.canon_packet, "Canon Packet")
        tabs.addTab(self.generated_chapter, "Generated Chapter")
        tabs.addTab(self.revision, "Revision")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(tabs)