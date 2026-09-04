"""Create and run the Tiresias Workstation Qt application."""

import sys

from PySide6.QtWidgets import QApplication

from tiresias_workstation.presentation.main_window import MainWindow
from tiresias_workstation.presentation.theme import apply_light_theme


def main() -> int:
    """Start the Tiresias Workstation application.

    Returns:
        Process exit code returned by Qt's application event loop.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("Tiresias Workstation")
    apply_light_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
