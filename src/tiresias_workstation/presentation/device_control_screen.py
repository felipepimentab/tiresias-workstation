"""Present connected-board identity and fixed DSP parameter control.

The screen consumes domain snapshots and correlated controller results. It
never handles characteristic UUIDs, packets, or raw DSP addresses.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tiresias_workstation.application.ble_controller import BleController
from tiresias_workstation.domain.dsp_contract import (
    DSP_BLOCKS_BY_ID,
    DspParameterDefinition,
)
from tiresias_workstation.domain.tiresias import (
    DeviceSession,
    ParameterValue,
    ProtocolCapability,
)

class DeviceControlScreen(QWidget):
    """Render device metadata and persistent parameter controls.

    Signals from the shared controller always arrive on Qt's UI thread. Reads
    are queued one at a time to respect the firmware's single-operation model.

    Attributes:
        _controller: Application coordinator owned by the main window.
        _session: Current validated device session, or ``None``.
        _pending_reads: Stable IDs awaiting a refresh operation.
        _operation_active: Whether the controller owns a parameter operation.
    """

    def __init__(self, controller: BleController) -> None:
        """Build an initially disconnected control surface.

        Args:
            controller: Shared BLE/application controller.
        """
        super().__init__()
        self._controller = controller
        self._session: DeviceSession | None = None
        self._definitions: dict[int, DspParameterDefinition] = {}
        self._stored_values: dict[int, ParameterValue] = {}
        self._pending_reads: list[int] = []
        self._operation_active = False
        self._build_ui()
        self._connect_signals()
        self._set_enabled(False)

    def show_board_information(self) -> None:
        """Select board information through the shared sidebar navigation."""
        self._pages.setCurrentIndex(0)
        self._title.setText("Board information")

    def show_parameters(self) -> None:
        """Select DSP parameters through the shared sidebar navigation."""
        self._pages.setCurrentIndex(1)
        self._title.setText("DSP parameters")

    def _build_ui(self) -> None:
        """Construct sidebar-addressable board and parameter pages."""
        self.setObjectName("deviceControlScreen")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 30)
        layout.setSpacing(14)

        self._title = QLabel("Board information")
        self._title.setObjectName("controlTitle")
        layout.addWidget(self._title)
        self._summary = QLabel("Connect to a compatible board from Devices.")
        self._summary.setObjectName("controlSummary")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._pages = QStackedWidget()
        self._pages.setObjectName("controlPages")
        self._pages.addWidget(self._build_board_page())
        self._pages.addWidget(self._build_parameter_page())
        layout.addWidget(self._pages, 1)

    def _build_board_page(self) -> QWidget:
        """Build the read-only identity and compatibility view."""
        page = QWidget()
        page.setObjectName("boardInformationPage")
        form = QFormLayout(page)
        form.setContentsMargins(24, 24, 24, 24)
        form.setHorizontalSpacing(28)
        form.setVerticalSpacing(13)
        self._board_values: dict[str, QLabel] = {}
        rows = (
            ("manufacturer", "Manufacturer"),
            ("model", "Model"),
            ("serial", "Serial number"),
            ("hardware", "Hardware revision"),
            ("firmware", "Firmware revision"),
            ("protocol", "Tiresias protocol"),
            ("layout", "DSP contract"),
            ("boot", "Boot/session ID"),
            ("revision", "Parameter revision"),
            ("behavior", "DSP behavior"),
        )
        for key, label_text in rows:
            value = QLabel("—")
            value.setObjectName(f"board_{key}")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            self._board_values[key] = value
            label = QLabel(label_text)
            label.setProperty("role", "fieldLabel")
            form.addRow(label, value)
        return page

    def _build_parameter_page(self) -> QWidget:
        """Build the fixed-contract table and ID-based controls."""
        page = QWidget()
        page.setObjectName("parameterPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._parameter_table = QTableWidget(0, 6)
        self._parameter_table.setObjectName("parameterTable")
        self._parameter_table.setHorizontalHeaderLabels(
            ["ID", "Block", "Parameter", "Access", "Bytes", "Current bytes"]
        )
        self._parameter_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._parameter_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._parameter_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._parameter_table.verticalHeader().hide()
        self._parameter_table.verticalHeader().setDefaultSectionSize(36)
        self._parameter_table.setShowGrid(False)
        self._parameter_table.setAlternatingRowColors(True)
        header = self._parameter_table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for column in (0, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self._parameter_table.setColumnWidth(5, 200)
        layout.addWidget(self._parameter_table, 1)

        editor = QFrame()
        editor.setObjectName("parameterEditor")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(16, 12, 16, 12)
        editor_layout.setSpacing(10)
        self._selected_parameter = QLabel("Select a DSP parameter")
        self._selected_parameter.setObjectName("selectedParameter")
        self._selected_parameter.setWordWrap(True)
        editor_layout.addWidget(self._selected_parameter)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._value_input = QLineEdit()
        self._value_input.setObjectName("parameterValueInput")
        self._value_input.setPlaceholderText("Hex bytes, for example: 00 00 00 01")
        self._value_input.setMinimumWidth(150)
        self._value_input.setAccessibleName("Parameter value in hexadecimal bytes")
        self._value_input.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        actions.addWidget(self._value_input, 1)

        self._read_button = QPushButton("Read")
        self._read_button.setObjectName("readParameterButton")
        actions.addWidget(self._read_button)
        self._write_button = QPushButton("Persist value")
        self._write_button.setObjectName("writeParameterButton")
        actions.addWidget(self._write_button)
        editor_layout.addLayout(actions)
        layout.addWidget(editor)

        status_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setObjectName("parameterProgress")
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(84)
        self._progress.hide()
        status_row.addWidget(self._progress)
        self._message = QLabel("Current DSP values are read after connection.")
        self._message.setObjectName("parameterMessage")
        self._message.setWordWrap(True)
        status_row.addWidget(self._message, 1)
        self._refresh_button = QPushButton("Refresh all")
        self._refresh_button.setObjectName("refreshParametersButton")
        status_row.addWidget(self._refresh_button)
        layout.addLayout(status_row)
        return page

    def _connect_signals(self) -> None:
        """Connect controller results and parameter user actions."""
        self._controller.session_loaded.connect(self._session_loaded)
        self._controller.disconnected.connect(self._disconnected)
        self._controller.parameter_read_started.connect(self._operation_started)
        self._controller.parameter_write_started.connect(self._write_started)
        self._controller.parameter_read.connect(self._parameter_received)
        self._controller.parameter_written.connect(self._parameter_written)
        self._controller.parameter_operation_failed.connect(self._operation_failed)
        self._parameter_table.itemSelectionChanged.connect(self._selection_changed)
        self._read_button.clicked.connect(self._read_selected)
        self._write_button.clicked.connect(self._write_selected)
        self._refresh_button.clicked.connect(self._refresh_all)

    @Slot(object)
    def _session_loaded(self, payload: object) -> None:
        """Render one validated device session and refresh current values."""
        if not isinstance(payload, DeviceSession):
            return
        self._session = payload
        self._stored_values.clear()
        self._definitions = {
            definition.parameter_id: definition for definition in payload.parameters
        }
        info = payload.information
        protocol = payload.protocol
        self._board_values["manufacturer"].setText(info.manufacturer or "Not reported")
        self._board_values["model"].setText(info.model_number or "Not reported")
        self._board_values["serial"].setText(info.serial_number or "Not reported")
        self._board_values["hardware"].setText(info.hardware_revision or "Not reported")
        self._board_values["firmware"].setText(info.firmware_revision or "Not reported")
        self._board_values["protocol"].setText(f"{protocol.major}.{protocol.minor}")
        self._board_values["layout"].setText(f"CRC32 0x{protocol.contract_crc32:08X}")
        self._board_values["boot"].setText(str(protocol.boot_id))
        self._board_values["revision"].setText(str(protocol.parameter_revision))
        deferred = bool(
            protocol.capabilities & ProtocolCapability.DSP_APPLY_DEFERRED
        )
        self._board_values["behavior"].setText(
            "Opaque-byte persistence enabled; DSP access deferred"
            if deferred
            else "Live DSP reads and persistent opaque-byte writes"
        )
        self._summary.setText(
            f"{info.model_number or 'Tiresias device'} · {len(payload.parameters)} "
            "fixed parameters · READY"
        )
        self._populate_parameters(payload.parameters)
        self._set_enabled(True)
        self._refresh_all()

    @Slot(str)
    def _disconnected(self, _address: str) -> None:
        """Clear session-scoped data after link loss or disconnection."""
        self._session = None
        self._definitions.clear()
        self._stored_values.clear()
        self._pending_reads.clear()
        self._operation_active = False
        self._progress.hide()
        self._parameter_table.setRowCount(0)
        self._summary.setText("Connect to a compatible board from Devices.")
        for value in self._board_values.values():
            value.setText("—")
        self._set_enabled(False)

    @Slot()
    def _selection_changed(self) -> None:
        """Configure the editor from the selected fixed definition."""
        definition = self._selected_definition()
        if definition is None:
            self._selected_parameter.setText("Select a DSP parameter")
        else:
            block = DSP_BLOCKS_BY_ID[definition.block_id]
            self._selected_parameter.setText(
                f"#{definition.parameter_id} · {block.name} · {definition.name}"
            )
            if definition.writable:
                current = self._stored_values.get(definition.parameter_id)
                self._value_input.setText(
                    current.data.hex(" ").upper() if current is not None else ""
                )
        self._update_actions()

    @Slot()
    def _read_selected(self) -> None:
        """Read the selected stable parameter identifier."""
        definition = self._selected_definition()
        if definition is None or not self._controller.read_parameter(
            definition.parameter_id
        ):
            self._show_message("Another operation is still in progress.", True)

    @Slot()
    def _write_selected(self) -> None:
        """Persist selected opaque bytes after fixed-contract validation."""
        definition = self._selected_definition()
        if definition is None:
            return
        try:
            data = bytes.fromhex(self._value_input.text())
        except ValueError:
            self._show_message("Enter parameter bytes as hexadecimal pairs.", True)
            return
        if not definition.accepts(data):
            self._show_message(
                f"Parameter {definition.parameter_id} requires "
                f"exactly {definition.byte_count} bytes.",
                True,
            )
            return
        if not self._controller.write_parameter(definition.parameter_id, data):
            self._show_message("Another operation is still in progress.", True)

    @Slot()
    def _refresh_all(self) -> None:
        """Queue one complete read per parameter without overlap."""
        if self._operation_active or self._session is None:
            return
        self._pending_reads = [entry.parameter_id for entry in self._session.parameters]
        self._read_next()

    @Slot(int)
    def _operation_started(self, _parameter_id: int) -> None:
        """Render an active parameter operation."""
        self._operation_active = True
        self._progress.show()
        self._update_actions()

    @Slot(int, object)
    def _write_started(self, parameter_id: int, _data: object) -> None:
        """Render an opaque-byte write without claiming completion."""
        self._operation_started(parameter_id)
        self._show_message(f"Writing parameter {parameter_id}…")

    @Slot(object)
    def _parameter_received(self, payload: object) -> None:
        """Render a correlated value and continue the queued refresh."""
        if not isinstance(payload, ParameterValue):
            return
        if self._session is None:
            return
        self._set_parameter_value(payload)
        self._operation_finished()
        self._read_next()

    @Slot(object)
    def _parameter_written(self, payload: object) -> None:
        """Render only a firmware-confirmed persistent write as success."""
        if not isinstance(payload, ParameterValue):
            return
        if self._session is None:
            return
        self._set_parameter_value(payload)
        self._board_values["revision"].setText(str(payload.parameter_revision))
        deferred = bool(
            self._session.protocol.capabilities
            & ProtocolCapability.DSP_APPLY_DEFERRED
        )
        suffix = "DSP application deferred" if deferred else "DSP updated"
        self._show_message(
            f"Persisted · revision {payload.parameter_revision} · {suffix}."
        )
        self._operation_finished()

    @Slot(int, str)
    def _operation_failed(self, parameter_id: int, message: str) -> None:
        """Render an actionable device or transport failure."""
        if self._session is None:
            return
        self._show_message(f"Parameter {parameter_id} failed: {message}", True)
        self._operation_finished()
        self._pending_reads.clear()

    def _read_next(self) -> None:
        """Schedule the next queued parameter read, if any."""
        if self._operation_active or not self._pending_reads:
            if not self._pending_reads and self._session is not None:
                self._show_message("DSP parameter values are up to date.")
            return
        parameter_id = self._pending_reads.pop(0)
        if not self._controller.read_parameter(parameter_id):
            self._pending_reads.clear()
            self._show_message("Could not schedule parameter refresh.", True)

    def _operation_finished(self) -> None:
        """Release presentation busy state after a terminal result."""
        self._operation_active = False
        self._progress.hide()
        self._update_actions()

    def _populate_parameters(
        self, parameters: tuple[DspParameterDefinition, ...]
    ) -> None:
        """Render fixed metadata while intentionally hiding DSP addresses."""
        self._parameter_table.setRowCount(len(parameters))
        for row, definition in enumerate(parameters):
            identifier = QTableWidgetItem(str(definition.parameter_id))
            identifier.setData(Qt.ItemDataRole.UserRole, definition.parameter_id)
            block = DSP_BLOCKS_BY_ID[definition.block_id]
            access = "Read · Write · Flash" if definition.writable else "Read"
            values = (
                identifier,
                QTableWidgetItem(block.name),
                QTableWidgetItem(definition.name),
                QTableWidgetItem(access),
                QTableWidgetItem(str(definition.byte_count)),
                QTableWidgetItem("Reading…"),
            )
            for column, item in enumerate(values):
                self._parameter_table.setItem(row, column, item)
        if parameters:
            self._parameter_table.selectRow(0)

    def _set_parameter_value(self, value: ParameterValue) -> None:
        """Update the current-byte cell and selected opaque-byte editor."""
        self._stored_values[value.parameter_id] = value
        definition = self._definitions.get(value.parameter_id)
        if definition is None:
            return
        for row in range(self._parameter_table.rowCount()):
            item = self._parameter_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == value.parameter_id:
                encoded = value.data.hex(" ").upper()
                if len(value.data) <= 8:
                    displayed = encoded
                else:
                    displayed = f"{len(value.data)} bytes · {encoded[:23]} … {encoded[-23:]}"
                value_item = self._parameter_table.item(row, 5)
                value_item.setText(displayed)
                value_item.setToolTip(encoded)
                if self._parameter_table.currentRow() == row and definition.writable:
                    self._value_input.setText(encoded)
                break

    def _selected_definition(self) -> DspParameterDefinition | None:
        """Return the selected fixed definition by stable ID."""
        row = self._parameter_table.currentRow()
        if row < 0:
            return None
        item = self._parameter_table.item(row, 0)
        if item is None:
            return None
        parameter_id = item.data(Qt.ItemDataRole.UserRole)
        return self._definitions.get(parameter_id)

    def _set_enabled(self, enabled: bool) -> None:
        """Enable session content only for a validated ready device."""
        self._pages.setEnabled(enabled)
        self._update_actions()

    def _update_actions(self) -> None:
        """Derive action availability from the fixed contract and busy state."""
        definition = self._selected_definition()
        connected = self._session is not None
        idle = connected and not self._operation_active
        self._read_button.setEnabled(bool(idle and definition))
        self._write_button.setEnabled(
            bool(idle and definition and definition.writable)
        )
        self._value_input.setVisible(bool(definition and definition.writable))
        self._value_input.setEnabled(self._write_button.isEnabled())
        self._refresh_button.setEnabled(idle)

    def _show_message(self, text: str, error: bool = False) -> None:
        """Render a contextual parameter-operation message."""
        self._message.setText(text)
        self._message.setProperty("error", error)
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
