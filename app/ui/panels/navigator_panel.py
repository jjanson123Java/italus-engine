from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem


class NavigatorPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Navigator")
        title.setObjectName("PanelTitle")

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)

        root = QTreeWidgetItem(["Project"])
        root.addChildren([
            QTreeWidgetItem(["Engine"]),
            QTreeWidgetItem(["Books"]),
            QTreeWidgetItem(["Events"]),
            QTreeWidgetItem(["Scenes"]),
            QTreeWidgetItem(["Templates"]),
            QTreeWidgetItem(["Characters"]),
            QTreeWidgetItem(["Memory"]),
            QTreeWidgetItem(["Archives"]),
        ])

        self.tree.addTopLevelItem(root)
        self.tree.expandAll()

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.tree)