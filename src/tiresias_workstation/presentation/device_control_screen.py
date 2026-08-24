"""Present connected-board identity and fixed DSP parameter control.

The screen consumes domain snapshots and correlated controller results. It
never handles characteristic UUIDs, packets, or raw DSP addresses.
"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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

_Q5_23_SCALE = 1 << 23


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
        """Select the board-information tab for sidebar navigation."""
        self._tabs.setCurrentIndex(0)

    def show_parameters(self) -> None:
        """Select the DSP-parameter tab for sidebar navigation."""
        self._tabs.setCurrentIndex(1)

    def _build_ui(self) -> None:
        """Construct the board and parameter tabs."""
        self.setObjectName("deviceControlScreen")
        self.setStyleSheet(_STYLE_SHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 30)
        layout.setSpacing(14)

        self._title = QLabel("Connected Tiresias DK")
        self._title.setObjectName("controlTitle")
        layout.addWidget(self._title)
        self._summary = QLabel("Connect to a compatible board from Devices.")
        self._summary.setObjectName("controlSummary")
        layout.addWidget(self._summary)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("controlTabs")
        self._tabs.addTab(self._build_board_tab(), "Board information")
        self._tabs.addTab(self._build_parameter_tab(), "DSP parameters")
        layout.addWidget(self._tabs, 1)

    def _build_board_tab(self) -> QWidget:
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
            self._board_values[key] = value
            form.addRow(label_text, value)
        return page

    def _build_parameter_tab(self) -> QWidget:
        """Build the fixed-contract table and ID-based controls."""
        page = QWidget()
        page.setObjectName("parameterPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self._parameter_table = QTableWidget(0, 6)
        self._parameter_table.setObjectName("parameterTable")
        self._parameter_table.setHorizontalHeaderLabels(
            ["ID", "Block", "Parameter", "Access", "Words", "Current value"]
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
        header = self._parameter_table.horizontalHeader()
        for column in (0, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._parameter_table, 1)

        editor = QFrame()
        editor.setObjectName("parameterEditor")
        editor_layout = QHBoxLayout(editor)
        editor_layout.setContentsMargins(14, 10, 10, 10)
        self._selected_parameter = QLabel("Select a DSP parameter")
        self._selected_parameter.setObjectName("selectedParameter")
        editor_layout.addWidget(self._selected_parameter, 1)

        self._value_input = QDoubleSpinBox()
        self._value_input.setObjectName("parameterValueInput")
        self._value_input.setDecimals(8)
        self._value_input.setMinimumWidth(150)
        editor_layout.addWidget(self._value_input)

        self._read_button = QPushButton("Read")
        self._read_button.setObjectName("readParameterButton")
        editor_layout.addWidget(self._read_button)
        self._write_button = QPushButton("Persist value")
        self._write_button.setObjectName("writeParameterButton")
        editor_layout.addWidget(self._write_button)
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
        self._board_values["layout"].setText(
            f"0x{protocol.contract_id:08X} · v{protocol.contract_version}"
        )
        self._board_values["boot"].setText(str(protocol.boot_id))
        self._board_values["revision"].setText(str(protocol.parameter_revision))
        deferred = bool(
            protocol.capabilities & ProtocolCapability.DSP_APPLY_DEFERRED
        )
        self._board_values["behavior"].setText(
            "Scalar persistence enabled; DSP access deferred"
            if deferred
            else "Live DSP reads and persistent scalar writes"
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
                minimum = definition.minimum
                maximum = definition.maximum
                step = definition.step
                default = definition.default
                assert minimum is not None
                assert maximum is not None
                assert step is not None
                assert default is not None
                self._value_input.setDecimals(0 if definition.integer else 8)
                self._value_input.setRange(
                    _raw_to_display(definition, minimum),
                    _raw_to_display(definition, maximum),
                )
                self._value_input.setSingleStep(
                    _raw_to_display(definition, step)
                )
                current = self._stored_values.get(definition.parameter_id)
                raw_value = current.value if current is not None else default
                self._value_input.setValue(
                    _raw_to_display(definition, raw_value)
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
        """Persist the selected scalar after fixed-contract validation."""
        definition = self._selected_definition()
        if definition is None:
            return
        raw_value = (
            round(self._value_input.value())
            if definition.integer
            else round(self._value_input.value() * _Q5_23_SCALE)
        )
        if not definition.accepts(raw_value):
            self._show_message("Value does not align with the contract step.", True)
            return
        if not self._controller.write_parameter(definition.parameter_id, raw_value):
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

    @Slot(int, int)
    def _write_started(self, parameter_id: int, _value: int) -> None:
        """Render a scalar write without claiming completion."""
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
                QTableWidgetItem(str(definition.word_count)),
                QTableWidgetItem("Reading…"),
            )
            for column, item in enumerate(values):
                self._parameter_table.setItem(row, column, item)
        if parameters:
            self._parameter_table.selectRow(0)

    def _set_parameter_value(self, value: ParameterValue) -> None:
        """Update the current-value cell and selected scalar editor."""
        self._stored_values[value.parameter_id] = value
        definition = self._definitions.get(value.parameter_id)
        if definition is None:
            return
        for row in range(self._parameter_table.rowCount()):
            item = self._parameter_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == value.parameter_id:
                if len(value.words) == 1:
                    displayed = _format_word(definition, value.value)
                    tooltip = f"Raw: 0x{value.value & 0xFFFFFFFF:08X}"
                else:
                    displayed = (
                        f"{len(value.words)} words · "
                        f"{_format_word(definition, value.words[0])} … "
                        f"{_format_word(definition, value.words[-1])}"
                    )
                    tooltip = "\n".join(
                        f"[{index}] {_format_word(definition, word)} "
                        f"(0x{word & 0xFFFFFFFF:08X})"
                        for index, word in enumerate(value.words)
                    )
                value_item = self._parameter_table.item(row, 5)
                value_item.setText(displayed)
                value_item.setToolTip(tooltip)
                if self._parameter_table.currentRow() == row and len(value.words) == 1:
                    self._value_input.setValue(
                        _raw_to_display(definition, value.value)
                    )
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
        self._tabs.setEnabled(enabled)
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


def _raw_to_display(definition: DspParameterDefinition, value: int) -> float:
    """Convert an encoded word to the unit displayed by the editor."""
    return float(value) if definition.integer else value / _Q5_23_SCALE


def _format_word(definition: DspParameterDefinition, value: int) -> str:
    """Format one encoded word according to the fixed type flag."""
    if definition.integer:
        return str(value)
    return f"{_raw_to_display(definition, value):.6f}"


_STYLE_SHEET = """
#deviceControlScreen, #boardInformationPage, #parameterPage {
    background: #ffffff;
    color: #202123;
}
#deviceControlScreen QLabel { color: #202123; }
#controlTitle { color: #202123; font-size: 24px; font-weight: 600; }
#controlSummary, #parameterMessage { color: #6e6e73; font-size: 13px; }
#parameterMessage[error="true"] { color: #c5221f; }
#controlTabs::pane, #parameterEditor {
    border: 1px solid #dedede; border-radius: 8px; background: #ffffff;
}
#controlTabs QTabBar::tab {
    background: #f1f1f3;
    color: #363638;
    min-width: 118px;
    padding: 6px 12px;
}
#controlTabs QTabBar::tab:selected {
    background: #2f80ed;
    color: #ffffff;
}
#parameterTable {
    alternate-background-color: #f7f7f8;
    background: #ffffff;
    border: 1px solid #dedede;
    color: #202123;
    font-size: 12px;
}
#parameterTable QHeaderView::section {
    background: #f1f1f3;
    color: #363638;
}
#parameterEditor QDoubleSpinBox {
    background: #ffffff;
    color: #202123;
}
#parameterEditor QPushButton, #refreshParametersButton {
    color: #202123;
}
#selectedParameter { font-size: 13px; font-weight: 500; }
QPushButton { min-height: 30px; padding: 0 12px; }
"""
