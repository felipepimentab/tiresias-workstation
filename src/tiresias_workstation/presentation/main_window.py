"""Define the top-level Tiresias Workstation window."""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tiresias_workstation.application.ble_controller import BleController
from tiresias_workstation.presentation.device_discovery_screen import (
    DeviceDiscoveryScreen,
)
from tiresias_workstation.presentation.device_control_screen import DeviceControlScreen


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
        self.device_control_screen = DeviceControlScreen(self._controller)
        self.setCentralWidget(self._build_application_shell())
        self.setStyleSheet(_WINDOW_STYLE_SHEET)
        self._controller.session_loaded.connect(self._session_available)
        self._controller.disconnected.connect(self._session_lost)

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

        self._devices_button = self._navigation_row("Devices", selected=True)
        self._devices_button.setObjectName("devicesNavigationButton")
        self._board_button = self._navigation_row("Board information", enabled=False)
        self._board_button.setObjectName("boardNavigationButton")
        self._parameters_button = self._navigation_row("DSP parameters", enabled=False)
        self._parameters_button.setObjectName("parametersNavigationButton")
        sidebar_layout.addWidget(self._devices_button)
        sidebar_layout.addWidget(self._board_button)
        sidebar_layout.addWidget(self._parameters_button)
        sidebar_layout.addWidget(self._navigation_row("Diagnostics", enabled=False))

        future_label = QLabel("LATER RELEASES")
        future_label.setObjectName("sidebarSectionLabel")
        sidebar_layout.addWidget(future_label)
        sidebar_layout.addWidget(self._navigation_row("Audiogram fitting", enabled=False))
        sidebar_layout.addWidget(self._navigation_row("DSP editor", enabled=False))
        sidebar_layout.addStretch()

        boundary = QLabel("Engineering tool\nNot for clinical use")
        boundary.setObjectName("productBoundary")
        sidebar_layout.addWidget(boundary)

        shell_layout.addWidget(sidebar)
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self.device_discovery_screen)
        self._content_stack.addWidget(self.device_control_screen)
        shell_layout.addWidget(self._content_stack, 1)

        self._devices_button.clicked.connect(self._show_devices)
        self._board_button.clicked.connect(self._show_board)
        self._parameters_button.clicked.connect(self._show_parameters)
        return shell

    @staticmethod
    def _navigation_row(
        text: str,
        *,
        selected: bool = False,
        enabled: bool = True,
    ) -> QPushButton:
        """Create a navigation row for an implemented or planned page.

        Args:
            text: Visible page label.
            selected: Whether the row represents the current page.
            enabled: Whether the destination is currently available.

        Returns:
            Configured sidebar row.
        """
        button = QPushButton(text)
        button.setObjectName("navigationButton")
        button.setProperty("selected", selected)
        button.setEnabled(enabled)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @Slot()
    def _show_devices(self) -> None:
        """Navigate to BLE discovery and connection controls."""
        self._content_stack.setCurrentWidget(self.device_discovery_screen)
        self._select_navigation(self._devices_button)

    @Slot()
    def _show_board(self) -> None:
        """Navigate to standard and custom board information."""
        self._content_stack.setCurrentWidget(self.device_control_screen)
        self.device_control_screen.show_board_information()
        self._select_navigation(self._board_button)

    @Slot()
    def _show_parameters(self) -> None:
        """Navigate to ID-based persistent DSP parameter control."""
        self._content_stack.setCurrentWidget(self.device_control_screen)
        self.device_control_screen.show_parameters()
        self._select_navigation(self._parameters_button)

    @Slot(object)
    def _session_available(self, _session: object) -> None:
        """Enable connected-device pages after protocol validation."""
        self._board_button.setEnabled(True)
        self._parameters_button.setEnabled(True)
        self._show_board()

    @Slot(str)
    def _session_lost(self, _address: str) -> None:
        """Return to Devices and disable session-scoped navigation."""
        self._board_button.setEnabled(False)
        self._parameters_button.setEnabled(False)
        self._show_devices()

    def _select_navigation(self, selected: QPushButton) -> None:
        """Update the active sidebar style for one implemented page."""
        for button in (
            self._devices_button,
            self._board_button,
            self._parameters_button,
        ):
            button.setProperty("selected", button is selected)
            button.style().unpolish(button)
            button.style().polish(button)

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
#sidebar QPushButton#navigationButton, #devicesNavigationButton,
#boardNavigationButton, #parametersNavigationButton {
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
#sidebar QPushButton[selected="true"] {
    background: #e5e5e5;
    color: #171717;
    font-weight: 500;
}
#sidebar QPushButton#navigationButton:disabled {
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
