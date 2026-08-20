"""Define the top-level Tiresias Workstation window."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from tiresias_workstation.application.ble_controller import BleController
from tiresias_workstation.presentation.device_discovery_screen import (
    DeviceDiscoveryScreen,
)


class MainWindow(QMainWindow):
    """Own application-level services and the active workstation screen."""

    def __init__(self, controller: BleController | None = None) -> None:
        """Initialize the workstation window.

        Args:
            controller: Optional controller for dependency injection. A real
                :class:`BleController` is created when omitted.
        """
        super().__init__()

        self._controller = controller or BleController()

        self.setWindowTitle("Tiresias Workstation")
        self.resize(1080, 720)
        self.setMinimumSize(820, 560)
        self.setDocumentMode(True)
        self.setUnifiedTitleAndToolBarOnMac(True)

        self.device_discovery_screen = DeviceDiscoveryScreen(self._controller)
        self.setCentralWidget(self._build_application_shell())
        self.setStyleSheet(_WINDOW_STYLE_SHEET)

    def _build_application_shell(self) -> QWidget:
        """Build the persistent navigation shell around the active page.

        Returns:
            Root widget containing the sidebar and discovery screen.
        """
        shell = QWidget()
        shell.setObjectName("applicationShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 14)
        sidebar_layout.setSpacing(3)

        brand = QLabel("Tiresias")
        brand.setObjectName("sidebarBrand")
        sidebar_layout.addWidget(brand)

        workspace_label = QLabel("WORKSTATION")
        workspace_label.setObjectName("sidebarSectionLabel")
        sidebar_layout.addWidget(workspace_label)

        devices_button = self._navigation_row("Devices", selected=True)
        devices_button.setObjectName("devicesNavigationButton")
        sidebar_layout.addWidget(devices_button)
        sidebar_layout.addWidget(self._navigation_row("Board information"))
        sidebar_layout.addWidget(self._navigation_row("DSP profiles"))
        sidebar_layout.addWidget(self._navigation_row("Diagnostics"))

        future_label = QLabel("LATER RELEASES")
        future_label.setObjectName("sidebarSectionLabel")
        sidebar_layout.addWidget(future_label)
        sidebar_layout.addWidget(self._navigation_row("Audiogram fitting"))
        sidebar_layout.addWidget(self._navigation_row("DSP editor"))
        sidebar_layout.addStretch()

        boundary = QLabel("Engineering tool\nNot for clinical use")
        boundary.setObjectName("productBoundary")
        sidebar_layout.addWidget(boundary)

        shell_layout.addWidget(sidebar)
        shell_layout.addWidget(self.device_discovery_screen, 1)
        return shell

    @staticmethod
    def _navigation_row(text: str, *, selected: bool = False) -> QLabel:
        """Create a navigation row for an implemented or planned page.

        Args:
            text: Visible page label.
            selected: Whether the row represents the current page.

        Returns:
            Configured sidebar row. Planned pages remain disabled.
        """
        label = QLabel(text)
        label.setObjectName("navigationButton")
        label.setProperty("selected", selected)
        label.setEnabled(selected)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return label

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Release Bluetooth resources before Qt destroys the window.

        Args:
            event: Qt close event passed to the base window implementation.
        """
        self._controller.shutdown()
        super().closeEvent(event)


_WINDOW_STYLE_SHEET = """
#applicationShell {
    background: #ffffff;
    color: #202123;
    font-family: "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
}
#sidebar {
    background: #f3f3f3;
    border: none;
    border-right: 1px solid #e4e4e4;
}
#sidebarBrand {
    color: #171717;
    font-size: 15px;
    font-weight: 600;
    padding: 5px 8px 18px 8px;
}
#sidebarSectionLabel {
    color: #8e8e93;
    font-size: 10px;
    font-weight: 600;
    padding: 18px 9px 6px 9px;
}
#sidebar QLabel#navigationButton, #devicesNavigationButton {
    background: transparent;
    border: none;
    border-radius: 7px;
    color: #363638;
    font-size: 13px;
    font-weight: 400;
    min-height: 34px;
    padding: 0 10px;
    text-align: left;
}
#devicesNavigationButton {
    background: #e5e5e5;
    color: #171717;
    font-weight: 500;
}
#sidebar QLabel#navigationButton:disabled {
    color: #a2a2a6;
}
#productBoundary {
    border-top: 1px solid #dddddf;
    color: #8e8e93;
    font-size: 11px;
    line-height: 1.4;
    padding: 14px 8px 3px 8px;
}
"""
