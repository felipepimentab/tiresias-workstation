"""Present Bluetooth discovery and connection controls.

The widget is intentionally a presentation layer: it renders
:class:`DiscoveredDevice` snapshots and forwards user intent to
:class:`BleController`, but never calls Bleak or constructs backend objects.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tiresias_workstation.application.ble_controller import BleController
from tiresias_workstation.domain.devices import DiscoveredDevice


class DeviceDiscoveryScreen(QWidget):
    """Present nearby BLE advertisements and connection controls.

    Attributes:
        _controller: Application coordinator that executes Bluetooth work.
        _devices: Latest advertisement snapshot indexed by device address.
        _connected_address: Confirmed connection address, or ``None``.
        _busy: Whether a scan or connection-state transition is active.
    """

    def __init__(self, controller: BleController) -> None:
        """Initialize the screen and subscribe to controller signals.

        Args:
            controller: Long-lived Bluetooth controller owned by the main
                window. The screen does not shut it down.
        """
        super().__init__()
        self._controller = controller
        self._devices: dict[str, DiscoveredDevice] = {}
        self._connected_address: str | None = None
        self._busy = False

        self._build_ui()
        self._connect_signals()
        self._update_controls()

    def _build_ui(self) -> None:
        """Construct and style the screen's static widget hierarchy."""
        self.setObjectName("deviceDiscoveryScreen")
        self.setStyleSheet(_STYLE_SHEET)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(36, 32, 36, 30)
        page_layout.setSpacing(16)

        heading_row = QHBoxLayout()
        heading_copy = QVBoxLayout()
        heading_copy.setSpacing(3)

        title = QLabel("Bluetooth devices")
        title.setObjectName("pageTitle")
        heading_copy.addWidget(title)

        subtitle = QLabel(
            "Find nearby BLE advertisers, then select one to attempt a connection."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        heading_copy.addWidget(subtitle)
        heading_row.addLayout(heading_copy, 1)

        self._status_badge = QLabel()
        self._status_badge.setObjectName("statusBadge")
        self._status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_badge.setMinimumWidth(112)
        heading_row.addWidget(self._status_badge, 0, Qt.AlignmentFlag.AlignTop)
        page_layout.addLayout(heading_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self._scan_button = QPushButton("Scan for devices")
        self._scan_button.setObjectName("scanButton")
        self._scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        toolbar.addWidget(self._scan_button)

        self._scan_progress = QProgressBar()
        self._scan_progress.setObjectName("scanProgress")
        self._scan_progress.setRange(0, 0)
        self._scan_progress.setFixedWidth(96)
        self._scan_progress.setTextVisible(False)
        self._scan_progress.hide()
        toolbar.addWidget(self._scan_progress)

        self._result_summary = QLabel("Ready to scan")
        self._result_summary.setObjectName("resultSummary")
        toolbar.addWidget(self._result_summary)
        toolbar.addStretch()
        page_layout.addLayout(toolbar)

        device_card = QFrame()
        device_card.setObjectName("deviceCard")
        card_layout = QVBoxLayout(device_card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.setSpacing(0)

        self._device_table = QTableWidget(0, 5)
        self._device_table.setObjectName("deviceTable")
        self._device_table.setHorizontalHeaderLabels(
            ["Device", "Identifier", "Signal", "Tiresias", "Advertised services"]
        )
        self._device_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._device_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._device_table.setAlternatingRowColors(True)
        self._device_table.setShowGrid(False)
        self._device_table.verticalHeader().hide()
        self._device_table.verticalHeader().setDefaultSectionSize(48)
        header = self._device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        card_layout.addWidget(self._device_table)
        page_layout.addWidget(device_card, 1)

        action_card = QFrame()
        action_card.setObjectName("actionCard")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(16, 12, 12, 12)
        action_layout.setSpacing(10)

        selection_copy = QVBoxLayout()
        selection_copy.setSpacing(2)
        selection_label = QLabel("Selected device")
        selection_label.setObjectName("selectionLabel")
        selection_copy.addWidget(selection_label)

        self._selection_detail = QLabel("Select a row to connect")
        self._selection_detail.setObjectName("selectionDetail")
        self._selection_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        selection_copy.addWidget(self._selection_detail)
        action_layout.addLayout(selection_copy, 1)

        self._disconnect_button = QPushButton("Disconnect")
        self._disconnect_button.setObjectName("disconnectButton")
        self._disconnect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        action_layout.addWidget(self._disconnect_button)

        self._connect_button = QPushButton("Connect")
        self._connect_button.setObjectName("connectButton")
        self._connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        action_layout.addWidget(self._connect_button)
        page_layout.addWidget(action_card)

        self._message = QLabel(
            "Scanning uses the operating system's Bluetooth adapter and may request "
            "Bluetooth permission."
        )
        self._message.setObjectName("messageLabel")
        self._message.setWordWrap(True)
        self._message.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        page_layout.addWidget(self._message)

        self._set_connection_status("Not connected", "idle")

    def _connect_signals(self) -> None:
        """Connect user actions and controller events to presentation slots."""
        self._scan_button.clicked.connect(self._start_scan)
        self._connect_button.clicked.connect(self._connect_selected)
        self._disconnect_button.clicked.connect(self._disconnect)
        self._device_table.itemSelectionChanged.connect(self._selection_changed)
        self._device_table.itemDoubleClicked.connect(self._connect_selected)

        self._controller.scan_started.connect(self._scan_started)
        self._controller.device_discovered.connect(self._device_discovered)
        self._controller.scan_finished.connect(self._scan_finished)
        self._controller.scan_failed.connect(self._scan_failed)
        self._controller.connection_started.connect(self._connection_started)
        self._controller.connection_succeeded.connect(self._connection_succeeded)
        self._controller.connection_failed.connect(self._connection_failed)
        self._controller.disconnection_started.connect(self._disconnection_started)
        self._controller.disconnected.connect(self._disconnected)

    @Slot()
    def _start_scan(self) -> None:
        """Forward a scan request and report immediate scheduling rejection."""
        if not self._controller.scan():
            self._show_message(
                "Another Bluetooth operation is still in progress.", True
            )

    @Slot()
    def _connect_selected(self) -> None:
        """Request a connection to the currently selected table row."""
        address = self._selected_address()
        if address is None:
            return
        device = self._devices.get(address)
        if device is None or not device.is_tiresias:
            self._show_message(
                "The selected advertisement does not include the Tiresias service.",
                True,
            )
            return
        if not self._controller.connect(address):
            self._show_message(
                "Another Bluetooth operation is still in progress.", True
            )

    @Slot()
    def _disconnect(self) -> None:
        """Request closure of the active connection."""
        if not self._controller.disconnect():
            self._show_message("There is no active connection to close.", True)

    @Slot()
    def _scan_started(self) -> None:
        """Reset stale results and render the active scanning state."""
        self._busy = True
        self._devices.clear()
        self._device_table.setRowCount(0)
        self._scan_progress.show()
        self._scan_button.setText("Scanning…")
        self._result_summary.setText("Listening for advertisements…")
        self._show_message("Keep the target device powered on and advertising.")
        self._update_controls()

    @Slot(object)
    def _device_discovered(self, device: object) -> None:
        """Insert or update one live advertisement row.

        Args:
            device: Signal payload expected to be a :class:`DiscoveredDevice`.
                Unexpected payload types are ignored defensively.
        """
        if not isinstance(device, DiscoveredDevice):
            return
        self._devices[device.address] = device
        row = self._row_for_address(device.address)
        if row is None:
            row = self._device_table.rowCount()
            self._device_table.insertRow(row)
        self._populate_row(row, device)

        count = len(self._devices)
        self._result_summary.setText(
            f"{count} device{'s' if count != 1 else ''} found…"
        )

    @Slot(object)
    def _scan_finished(self, devices: object) -> None:
        """Render final discovery count and restore available controls.

        Args:
            devices: Final device list supplied by the controller.
        """
        self._busy = False
        self._scan_progress.hide()
        self._scan_button.setText("Scan again")

        count = len(devices) if isinstance(devices, list) else len(self._devices)
        self._result_summary.setText(
            f"{count} device{'s' if count != 1 else ''} found"
        )
        if count == 0:
            self._show_message(
                "No advertising BLE devices were found. Move closer and scan again."
            )
        else:
            self._show_message("Select a device to attempt a connection.")
        self._update_controls()

    @Slot(str)
    def _scan_failed(self, message: str) -> None:
        """Render a scan error while leaving discovery retryable.

        Args:
            message: User-displayable error from the platform backend.
        """
        self._busy = False
        self._scan_progress.hide()
        self._scan_button.setText("Try scan again")
        self._result_summary.setText("Scan failed")
        self._show_message(f"Could not scan: {message}", True)
        self._update_controls()

    @Slot(str)
    def _connection_started(self, address: str) -> None:
        """Render an in-progress connection attempt.

        Args:
            address: Platform identifier of the target device.
        """
        self._busy = True
        device = self._devices.get(address)
        name = self._display_name(device) if device is not None else address
        self._set_connection_status("Connecting…", "working")
        self._show_message(f"Attempting to connect to {name}…")
        self._update_controls()

    @Slot(str)
    def _connection_succeeded(self, address: str) -> None:
        """Render a confirmed connection and expose disconnection controls.

        Args:
            address: Platform identifier of the connected device.
        """
        self._busy = False
        self._connected_address = address
        device = self._devices.get(address)
        name = self._display_name(device) if device is not None else address
        self._set_connection_status("Connected", "connected")
        self._show_message(f"Connected to {name}.")
        self._update_controls()

    @Slot(str, str)
    def _connection_failed(self, address: str, message: str) -> None:
        """Render a failed connect or disconnect operation.

        Args:
            address: Device involved in the failed operation.
            message: User-displayable error from the transport.
        """
        self._busy = False
        if self._connected_address == address:
            self._set_connection_status("Connected", "connected")
        else:
            self._set_connection_status("Not connected", "idle")
        self._show_message(f"Connection operation failed: {message}", True)
        self._update_controls()

    @Slot(str)
    def _disconnection_started(self, address: str) -> None:
        """Render an in-progress explicit disconnection.

        Args:
            address: Platform identifier of the connected device.
        """
        self._busy = True
        self._set_connection_status("Disconnecting…", "working")
        self._show_message(f"Closing the connection to {address}…")
        self._update_controls()

    @Slot(str)
    def _disconnected(self, address: str) -> None:
        """Render an expected disconnect or unexpected link loss.

        Args:
            address: Platform identifier whose connection closed.
        """
        was_expected = self._busy
        self._busy = False
        self._connected_address = None
        self._set_connection_status("Not connected", "idle")
        self._show_message(
            (
                "Disconnected."
                if was_expected
                else f"The connection to {address} was lost."
            ),
            not was_expected,
        )
        self._update_controls()

    @Slot()
    def _selection_changed(self) -> None:
        """Update the selected-device summary and connection availability."""
        address = self._selected_address()
        device = self._devices.get(address) if address is not None else None
        if device is None:
            self._selection_detail.setText("Select a row to connect")
        else:
            self._selection_detail.setText(
                f"{self._display_name(device)}  ·  {device.address}  ·  "
                f"{'Supported' if device.is_tiresias else 'Not a Tiresias device'}"
            )
        self._update_controls()

    def _populate_row(self, row: int, device: DiscoveredDevice) -> None:
        """Write one normalized device snapshot into a table row.

        Args:
            row: Zero-based destination row.
            device: Latest advertisement snapshot to display.
        """
        name_item = QTableWidgetItem(self._display_name(device))
        name_item.setData(Qt.ItemDataRole.UserRole, device.address)
        if device.name is None:
            name_item.setForeground(QColor("#8e8e93"))

        address_item = QTableWidgetItem(device.address)
        signal_item = QTableWidgetItem(self._format_signal(device.rssi))
        identity_item = QTableWidgetItem("Supported" if device.is_tiresias else "—")
        if device.is_tiresias:
            identity_item.setForeground(QColor("#16803a"))

        services = [self._short_uuid(uuid) for uuid in device.service_uuids]
        if services:
            visible_services = ", ".join(services[:2])
            if len(services) > 2:
                visible_services += f"  +{len(services) - 2}"
        else:
            visible_services = "—"
        services_item = QTableWidgetItem(visible_services)
        services_item.setToolTip("\n".join(device.service_uuids))

        for column, item in enumerate(
            (name_item, address_item, signal_item, identity_item, services_item)
        ):
            self._device_table.setItem(row, column, item)

    def _row_for_address(self, address: str) -> int | None:
        """Find the row holding an address.

        Args:
            address: Platform device identifier to locate.

        Returns:
            Zero-based row index, or ``None`` when absent.
        """
        for row in range(self._device_table.rowCount()):
            item = self._device_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == address:
                return row
        return None

    def _selected_address(self) -> str | None:
        """Return the selected device address, if a valid row is selected."""
        row = self._device_table.currentRow()
        if row < 0:
            return None
        item = self._device_table.item(row, 0)
        if item is None:
            return None
        address = item.data(Qt.ItemDataRole.UserRole)
        return address if isinstance(address, str) else None

    def _update_controls(self) -> None:
        """Derive button and table availability from current screen state."""
        has_selection = self._selected_address() is not None
        selected = self._devices.get(self._selected_address() or "")
        supported_selection = selected is not None and selected.is_tiresias
        is_connected = self._connected_address is not None
        self._scan_button.setEnabled(not self._busy and not is_connected)
        self._device_table.setEnabled(not self._busy and not is_connected)
        self._connect_button.setVisible(not is_connected)
        self._connect_button.setEnabled(
            has_selection and supported_selection and not self._busy
        )
        self._disconnect_button.setVisible(is_connected)
        self._disconnect_button.setEnabled(is_connected and not self._busy)

    def _set_connection_status(self, text: str, state: str) -> None:
        """Update badge text and its dynamic stylesheet state.

        Args:
            text: Human-readable status label.
            state: Stylesheet state: ``idle``, ``working``, or ``connected``.
        """
        indicator = {
            "idle": "○",
            "working": "●",
            "connected": "●",
        }[state]
        self._status_badge.setText(f"{indicator}  {text}")
        self._status_badge.setProperty("connectionState", state)
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)

    def _show_message(self, text: str, is_error: bool = False) -> None:
        """Show contextual guidance or an error below the controls.

        Args:
            text: Message to display.
            is_error: Whether to apply the error presentation style.
        """
        self._message.setText(text)
        self._message.setProperty("error", is_error)
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)

    @staticmethod
    def _display_name(device: DiscoveredDevice) -> str:
        """Return an advertisement name with a stable unnamed fallback."""
        return device.name or "Unnamed device"

    @staticmethod
    def _format_signal(rssi: int) -> str:
        """Format RSSI in dBm with a coarse human-readable quality label."""
        if rssi >= -60:
            quality = "Strong"
        elif rssi >= -75:
            quality = "Good"
        elif rssi >= -90:
            quality = "Weak"
        else:
            quality = "Very weak"
        return f"{rssi} dBm  ·  {quality}"

    @staticmethod
    def _short_uuid(uuid: str) -> str:
        """Collapse a Bluetooth SIG base UUID to its assigned 16-bit value."""
        suffix = "-0000-1000-8000-00805f9b34fb"
        if uuid.startswith("0000") and uuid.endswith(suffix):
            return uuid[4:8].upper()
        return uuid


_STYLE_SHEET = """
#deviceDiscoveryScreen {
    background: #ffffff;
    color: #202123;
    font-family: "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
}
#pageTitle {
    color: #202123;
    font-size: 24px;
    font-weight: 600;
}
#pageSubtitle, #resultSummary, #messageLabel {
    color: #6e6e73;
    font-size: 13px;
}
#messageLabel[error="true"] {
    color: #c5221f;
}
#statusBadge {
    background: transparent;
    border: none;
    font-size: 12px;
    font-weight: 500;
    padding: 6px 4px;
}
#statusBadge[connectionState="idle"] {
    color: #8e8e93;
}
#statusBadge[connectionState="working"] {
    color: #b26800;
}
#statusBadge[connectionState="connected"] {
    color: #16803a;
}
#deviceCard, #actionCard {
    background: #ffffff;
    border: 1px solid #dedede;
    border-radius: 8px;
}
#deviceTable {
    background: transparent;
    alternate-background-color: #fbfbfb;
    border: none;
    border-radius: 8px;
    color: #2c2c2e;
    font-size: 12px;
    selection-background-color: #eeeeef;
    selection-color: #171717;
}
#deviceTable::item {
    border: none;
    padding: 7px 10px;
}
#deviceTable QHeaderView::section {
    background: #fafafa;
    border: none;
    border-bottom: 1px solid #e3e3e3;
    color: #6e6e73;
    font-size: 11px;
    font-weight: 500;
    padding: 9px 10px;
}
#selectionLabel {
    color: #8e8e93;
    font-size: 11px;
    font-weight: 500;
}
#selectionDetail {
    color: #2c2c2e;
    font-size: 13px;
    font-weight: 500;
}
QPushButton {
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    min-height: 32px;
    padding: 0 14px;
}
#scanButton, #connectButton {
    background: #202123;
    border: 1px solid #202123;
    color: #ffffff;
}
#scanButton:hover, #connectButton:hover {
    background: #343437;
    border-color: #343437;
}
#scanButton:pressed, #connectButton:pressed {
    background: #111111;
}
#disconnectButton {
    background: #f7f7f7;
    border: 1px solid #d5d5d5;
    color: #2c2c2e;
}
#disconnectButton:hover {
    background: #ededed;
}
QPushButton:disabled {
    background: #f1f1f1;
    border-color: #e5e5e5;
    color: #a2a2a6;
}
#scanProgress {
    background: #e7e7e7;
    border: none;
    border-radius: 2px;
    max-height: 4px;
}
#scanProgress::chunk {
    background: #6e6e73;
    border-radius: 2px;
}
"""
