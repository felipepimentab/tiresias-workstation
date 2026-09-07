"""Define the top-level Tiresias Workstation window."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Slot
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
from tiresias_workstation.application.fitting_library import FittingLibrary
from tiresias_workstation.presentation.fitting_library_screen import FittingLibraryScreen, PAGE_LABELS
from tiresias_workstation.domain.library import LIBRARY_KINDS
from tiresias_workstation.application.default_prescriptions import (
    create_default_prescription_services,
)
from tiresias_workstation.application.prescription_workbench import (
    PrescriptionWorkbench,
)
from tiresias_workstation.domain.prescriptions import PrescriptionCatalog
from tiresias_workstation.domain.tiresias import DeviceSession
from tiresias_workstation.presentation.device_discovery_screen import (
    DeviceDiscoveryScreen,
)
from tiresias_workstation.presentation.device_control_screen import DeviceControlScreen


class MainWindow(QMainWindow):
    """Own application-level services and the active workstation screen."""

    def __init__(
        self,
        controller: BleController | None = None,
        prescription_catalog: PrescriptionCatalog | None = None,
        prescription_workbench: PrescriptionWorkbench | None = None,
        fitting_library: FittingLibrary | None = None,
    ) -> None:
        """Initialize the workstation window.

        Args:
            controller: Optional controller for dependency injection. A real
                :class:`BleController` is created when omitted.
            prescription_catalog: Legacy catalog argument retained for constructor
                compatibility. Object pages use the fitting library.
            prescription_workbench: Optional custom fitting coordinator for
                tests or alternate rule and storage configurations.
            fitting_library: Optional independent object library for tests or alternate storage.
        """
        super().__init__()

        self._controller = controller or BleController()
        self._connected_address: str | None = None
        self._connected_device_details = ""
        self._session_connected = False
        storage_directory = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
        ) / "generated-prescriptions"
        default_workbench = default_catalog = None
        if prescription_workbench is None or prescription_catalog is None or (
            fitting_library is None and prescription_workbench.library is None
        ):
            default_workbench, default_catalog = create_default_prescription_services(
                storage_directory
            )
        self._prescription_catalog = prescription_catalog or default_catalog
        self._prescription_workbench = prescription_workbench or default_workbench
        library = fitting_library or self._prescription_workbench.library
        if library is None:
            library = default_workbench.library

        self.setWindowTitle("Tiresias Workstation")
        self.setMinimumSize(960, 680)
        available = self.screen().availableGeometry()
        # Qt excludes the menu bar and Dock; leave room for the window frame
        # and a small desktop margin without maximizing the window.
        self.resize(min(1440, available.width() - 32),
                    min(900, available.height() - 48))
        self.setDocumentMode(True)
        self.setUnifiedTitleAndToolBarOnMac(True)

        self.device_discovery_screen = DeviceDiscoveryScreen(self._controller)
        self.device_control_screen = DeviceControlScreen(self._controller)
        self.object_screens = {
            kind: FittingLibraryScreen(library, self._controller, kind=kind)
            for kind in LIBRARY_KINDS
        }
        for screen in self.object_screens.values():
            screen.changed.connect(self._refresh_objects)
        self.setCentralWidget(self._build_application_shell())
        self._controller.connection_started.connect(self._connection_started)
        self._controller.connection_succeeded.connect(self._connection_succeeded)
        self._controller.connection_failed.connect(self._connection_failed)
        self._controller.disconnection_started.connect(self._disconnection_started)
        self._controller.session_loaded.connect(self._session_available)
        self._controller.disconnected.connect(self._session_lost)

    def _build_application_shell(self) -> QWidget:
        """Build the persistent navigation shell around the active page.

        Returns:
            Root widget containing persistent navigation, connection header,
            and active screen.
        """
        shell = QWidget()
        shell.setObjectName("applicationShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
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
        self._object_buttons = {}
        for group, kinds in (("REFERENCE & DESIGN", LIBRARY_KINDS[:3]),
                             ("LOAD TO BOARD", LIBRARY_KINDS[3:])):
            label = QLabel(group)
            label.setObjectName("sidebarSectionLabel")
            sidebar_layout.addWidget(label)
            for kind in kinds:
                button = self._navigation_row(PAGE_LABELS[kind])
                button.setObjectName(f"{kind}NavigationButton")
                button.setProperty("boardLoadable", kind in ("compiled", "outputs"))
                button.clicked.connect(lambda _checked=False, selected=kind: self._show_object(selected))
                sidebar_layout.addWidget(button)
                self._object_buttons[kind] = button
        sidebar_layout.addStretch()

        boundary = QLabel("Engineering tool\nNot for clinical use")
        boundary.setObjectName("productBoundary")
        sidebar_layout.addWidget(boundary)

        shell_layout.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("mainContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_connection_header())

        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self.device_discovery_screen)
        self._content_stack.addWidget(self.device_control_screen)
        for screen in self.object_screens.values():
            self._content_stack.addWidget(screen)
        content_layout.addWidget(self._content_stack, 1)
        shell_layout.addWidget(content, 1)

        self._devices_button.clicked.connect(self._show_devices)
        self._board_button.clicked.connect(self._show_board)
        self._parameters_button.clicked.connect(self._show_parameters)
        return shell

    def _build_connection_header(self) -> QFrame:
        """Build the status banner that remains visible on every screen."""
        header = QFrame()
        header.setObjectName("connectionHeader")
        header.setMinimumHeight(70)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 11, 24, 11)
        layout.setSpacing(14)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        label = QLabel("DEVICE CONNECTION")
        label.setObjectName("connectionHeaderLabel")
        copy.addWidget(label)
        self._connection_details = QLabel("No Tiresias board connected")
        self._connection_details.setObjectName("connectionHeaderDetails")
        self._connection_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        copy.addWidget(self._connection_details)
        layout.addLayout(copy, 1)

        self._connection_badge = QLabel("Not connected")
        self._connection_badge.setObjectName("connectionHeaderBadge")
        self._connection_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._connection_badge.setProperty("connectionState", "idle")
        layout.addWidget(self._connection_badge)
        return header

    def _set_connection_header(
        self, status: str, details: str, state: str
    ) -> None:
        """Update persistent connection copy and its semantic visual state.

        Args:
            status: Short connection lifecycle label.
            details: Device identity or actionable status context.
            state: Stylesheet state name such as ``connected`` or ``working``.
        """
        self._connection_badge.setText(status)
        self._connection_badge.setProperty("connectionState", state)
        self._connection_badge.style().unpolish(self._connection_badge)
        self._connection_badge.style().polish(self._connection_badge)
        self._connection_details.setText(details)

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

    def _show_object(self, kind: str) -> None:
        """Open one data object page, available both online and offline."""
        screen = self.object_screens[kind]
        screen.refresh()
        self._content_stack.setCurrentWidget(screen)
        self._select_navigation(self._object_buttons[kind])

    @Slot()
    def _refresh_objects(self) -> None:
        """Keep source references and object lists synchronized after CRUD."""
        for screen in self.object_screens.values():
            screen.refresh()

    @Slot(str)
    def _connection_started(self, address: str) -> None:
        """Show an in-progress connection in the persistent header."""
        self._connected_address = address
        self._set_connection_header("Connecting…", address, "working")

    @Slot(str)
    def _connection_succeeded(self, address: str) -> None:
        """Show a validated connection while identity details arrive."""
        self._connected_address = address
        self._session_connected = True
        self._connected_device_details = address
        self._set_connection_header("Connected", address, "connected")

    @Slot(str, str)
    def _connection_failed(self, address: str, message: str) -> None:
        """Show a connection failure without enabling session pages."""
        if self._session_connected:
            self._set_connection_header(
                "Connected",
                self._connected_device_details or address,
                "connected",
            )
            return
        self._connected_address = None
        self._set_connection_header(
            "Connection failed", f"{address} · {message}", "error"
        )

    @Slot(str)
    def _disconnection_started(self, address: str) -> None:
        """Show an explicit disconnection while it is in progress."""
        self._set_connection_header("Disconnecting…", address, "working")

    @Slot(object)
    def _session_available(self, payload: object) -> None:
        """Enable connected-device pages and publish available identity."""
        if isinstance(payload, DeviceSession):
            self._session_connected = True
            info = payload.information
            details = [info.model_number or "Tiresias device"]
            if info.serial_number:
                details.append(f"Serial {info.serial_number}")
            if info.firmware_revision:
                details.append(f"Firmware {info.firmware_revision}")
            if self._connected_address:
                details.append(self._connected_address)
            self._connected_device_details = " · ".join(details)
            self._set_connection_header(
                "Connected", self._connected_device_details, "connected"
            )
        self._board_button.setEnabled(True)
        self._parameters_button.setEnabled(True)
        if self._content_stack.currentWidget() not in self.object_screens.values():
            self._show_board()

    @Slot(str)
    def _session_lost(self, _address: str) -> None:
        """Return to Devices and disable session-scoped navigation."""
        self._connected_address = None
        self._connected_device_details = ""
        self._session_connected = False
        self._set_connection_header(
            "Not connected", "No Tiresias board connected", "idle"
        )
        self._board_button.setEnabled(False)
        self._parameters_button.setEnabled(False)
        if self._content_stack.currentWidget() not in self.object_screens.values():
            self._show_devices()

    def _select_navigation(self, selected: QPushButton) -> None:
        """Update the active sidebar style for one implemented page."""
        for button in (
            self._devices_button,
            self._board_button,
            self._parameters_button,
            *self._object_buttons.values(),
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
