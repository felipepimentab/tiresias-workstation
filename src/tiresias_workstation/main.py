"""Create and run the Tiresias Workstation Qt application."""

import sys

from PySide6.QtWidgets import QApplication

from tiresias_workstation.main_window import MainWindow


def main() -> int:
    """Start the Tiresias Workstation application.

    Returns:
        Process exit code returned by Qt's application event loop.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("Tiresias Workstation")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
