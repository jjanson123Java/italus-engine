from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
)


class ProjectTile(QFrame):
    clicked = Signal(str)

    def __init__(self, title: str, subtitle: str, mode: str) -> None:
        super().__init__()

        self.mode = mode
        self.setObjectName("ProjectTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(300, 190)

        title_label = QLabel(title)
        title_label.setObjectName("TileTitle")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("TileSubtitle")
        subtitle_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.mode)
        super().mousePressEvent(event)


class LandingPage(QWidget):
    new_project_requested = Signal(str)
    existing_project_requested = Signal(str)
    archived_project_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Narrative Studio")
        title.setObjectName("LandingTitle")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Canon-controlled narrative creation platform")
        subtitle.setObjectName("LandingSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)

        new_tile = ProjectTile(
            "New Project",
            "Start with a clean project context and choose a narrative template.",
            "new",
        )
        existing_tile = ProjectTile(
            "Existing Project",
            "Load an active project and resume canon, scenes, prompts, and continuity.",
            "existing",
        )
        archived_tile = ProjectTile(
            "Archived Project",
            "Open or restore a completed or parked project.",
            "archived",
        )

        new_tile.clicked.connect(self.new_project_requested.emit)
        existing_tile.clicked.connect(self.existing_project_requested.emit)
        archived_tile.clicked.connect(self.archived_project_requested.emit)

        tile_row = QHBoxLayout()
        tile_row.setSpacing(24)
        tile_row.addStretch()
        tile_row.addWidget(new_tile)
        tile_row.addWidget(existing_tile)
        tile_row.addWidget(archived_tile)
        tile_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 80, 60, 80)
        layout.setSpacing(28)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(36)
        layout.addLayout(tile_row)
        layout.addStretch()