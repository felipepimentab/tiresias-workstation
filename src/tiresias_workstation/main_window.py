from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    """Top-level window for Tiresias Workstation."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Tiresias Workstation")
        self.resize(640, 400)

        greeting = QLabel("Hello, world!")
        greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(greeting)
