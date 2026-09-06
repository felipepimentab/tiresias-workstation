"""Present connected-board identity and fixed DSP parameter control.

The screen consumes domain snapshots and correlated controller results. It
never handles characteristic UUIDs, packets, or raw DSP addresses.
"""

from math import log10

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontDatabase,
    QLinearGradient,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
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
    DspParameterId,
)
from tiresias_workstation.domain.dsp_values import (
    decode_sigma_5_23_words,
    decode_u32_word,
    encode_u32_word,
)
from tiresias_workstation.domain.tiresias import (
    DeviceSession,
    ParameterValue,
    ProtocolCapability,
)


_COMPRESSOR_PARAMETER_IDS = frozenset(range(3, 11))
_GAIN_PARAMETER_IDS = frozenset(range(11, 15))
_COMPRESSOR_INPUT_LEVELS_DBFS = (
    -90.0,
    -90.0,
    *tuple(float(value) for value in range(-87, 7, 3)),
)
_COMPRESSOR_X_MIN_DBFS = -90.0
_COMPRESSOR_X_MAX_DBFS = 6.0
_COMPRESSOR_Y_MIN_DBFS = -113.0
_COMPRESSOR_Y_MAX_DBFS = 27.0

_EDITOR_EMPTY = 0
_EDITOR_ADC_SELECT = 1
_EDITOR_SOURCE_SELECT = 2
_EDITOR_COMPRESSOR = 3
_EDITOR_GAIN = 4
_EDITOR_RAW = 5


class CompressorCurveWidget(QWidget):
    """Paint a lightweight line graph of decoded compressor LUT values."""

    def __init__(self) -> None:
        """Create an empty graph with a useful minimum inspection size."""
        super().__init__()
        self._values: tuple[float, ...] = ()
        self._points_dbfs: tuple[tuple[float, float], ...] = ()
        self.setObjectName("compressorCurve")
        self.setMinimumHeight(210)

    @property
    def values(self) -> tuple[float, ...]:
        """Return the currently displayed dimensionless LUT values."""
        return self._values

    @property
    def points_dbfs(self) -> tuple[tuple[float, float], ...]:
        """Return plotted input/output coordinates in dBFS."""
        return self._points_dbfs

    def set_values(self, values: tuple[float, ...]) -> None:
        """Replace plotted values without changing their stored DSP bytes.

        Args:
            values: Dimensionless values decoded from SigmaDSP 5.23 words.
        """
        self._values = values
        self._points_dbfs = tuple(
            (
                input_level,
                (
                    input_level + 20.0 * log10(linear_gain)
                    if linear_gain > 0.0
                    else _COMPRESSOR_Y_MIN_DBFS
                ),
            )
            for input_level, linear_gain in zip(
                _COMPRESSOR_INPUT_LEVELS_DBFS, values
            )
        )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Paint axes, value labels, and the current compressor curve.

        Args:
            event: Qt paint event describing the invalidated region.
        """
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        plot = QRectF(self.rect()).adjusted(42.0, 12.0, -10.0, -26.0)
        if plot.width() <= 0 or plot.height() <= 0:
            return

        label_pen = QPen(QColor("#667382"))
        grid_pen = QPen(QColor("#c4c9d0"))
        grid_pen.setWidthF(1.0)
        for input_level in range(-90, 1, 10):
            x = self._x_position(plot, float(input_level))
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(label_pen)
            painter.drawText(
                QRectF(x - 18.0, plot.bottom() + 3.0, 36.0, 18.0),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                str(input_level),
            )

        for output_level in range(-100, 21, 20):
            y = self._y_position(plot, float(output_level))
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(label_pen)
            painter.drawText(
                QRectF(0.0, y - 9.0, plot.left() - 6.0, 18.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(output_level),
            )

        painter.setPen(label_pen)
        painter.drawText(
            QRectF(0.0, plot.bottom() - 9.0, plot.left() - 6.0, 18.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "-113",
        )
        if not self._points_dbfs:
            painter.drawText(
                plot, Qt.AlignmentFlag.AlignCenter, "Read to display curve"
            )
            painter.setPen(QPen(QColor("#7f8b99")))
            painter.drawRect(plot)
            return

        curve = QPainterPath()
        for index, (input_level, output_level) in enumerate(self._points_dbfs):
            x = self._x_position(plot, input_level)
            y = self._y_position(plot, output_level)
            point = QPointF(x, y)
            if index == 0:
                curve.moveTo(point)
            else:
                curve.lineTo(point)

        fill = QPainterPath(curve)
        last_x = self._x_position(plot, self._points_dbfs[-1][0])
        first_x = self._x_position(plot, self._points_dbfs[0][0])
        fill.lineTo(last_x, plot.bottom())
        fill.lineTo(first_x, plot.bottom())
        fill.closeSubpath()
        gradient = QLinearGradient(plot.topLeft(), plot.bottomLeft())
        gradient.setColorAt(0.0, QColor(92, 151, 230, 35))
        gradient.setColorAt(1.0, QColor(92, 151, 230, 115))
        painter.fillPath(fill, QBrush(gradient))

        curve_pen = QPen(QColor("#6f7d8e"))
        curve_pen.setWidthF(1.25)
        painter.setPen(curve_pen)
        painter.drawPath(curve)

        emphasized = frozenset((0, 7, 16, 24, len(self._points_dbfs) - 1))
        for index, (input_level, output_level) in enumerate(self._points_dbfs):
            centre = QPointF(
                self._x_position(plot, input_level),
                self._y_position(plot, output_level),
            )
            if index in emphasized:
                painter.setPen(QPen(QColor("#233b75"), 1.0))
                painter.setBrush(QColor("#6b98ef"))
                painter.drawEllipse(centre, 4.7, 4.7)
            else:
                painter.setPen(QPen(QColor("#6f7d8e"), 0.8))
                painter.setBrush(QColor("#b9c4d1"))
                painter.drawEllipse(centre, 1.6, 1.6)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#7f8b99"), 1.0))
        painter.drawRect(plot)

    @staticmethod
    def _x_position(plot: QRectF, input_level_dbfs: float) -> float:
        """Map a compressor input level in dBFS to the graph rectangle."""
        ratio = (input_level_dbfs - _COMPRESSOR_X_MIN_DBFS) / (
            _COMPRESSOR_X_MAX_DBFS - _COMPRESSOR_X_MIN_DBFS
        )
        return plot.left() + ratio * plot.width()

    @staticmethod
    def _y_position(plot: QRectF, output_level_dbfs: float) -> float:
        """Map a compressor output level in dBFS to the graph rectangle."""
        bounded = min(
            max(output_level_dbfs, _COMPRESSOR_Y_MIN_DBFS),
            _COMPRESSOR_Y_MAX_DBFS,
        )
        ratio = (bounded - _COMPRESSOR_Y_MIN_DBFS) / (
            _COMPRESSOR_Y_MAX_DBFS - _COMPRESSOR_Y_MIN_DBFS
        )
        return plot.bottom() - ratio * plot.height()


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
        """Build the fixed-contract table and right-side parameter inspector."""
        page = QWidget()
        page.setObjectName("parameterPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("parameterWorkspace")
        splitter.setChildrenCollapsible(False)

        self._parameter_table = QTableWidget(0, 6)
        self._parameter_table.setObjectName("parameterTable")
        self._parameter_table.setHorizontalHeaderLabels(
            ["ID", "Block", "Parameter", "Access", "Bytes", "Current value"]
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
        for column in (0, 1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self._parameter_table)

        editor = QFrame()
        editor.setObjectName("parameterInspector")
        editor.setMinimumWidth(310)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(18, 16, 18, 16)
        editor_layout.setSpacing(9)
        inspector_label = QLabel("PARAMETER INSPECTOR")
        inspector_label.setObjectName("parameterInspectorLabel")
        editor_layout.addWidget(inspector_label)
        self._selected_parameter = QLabel("Select a DSP parameter")
        self._selected_parameter.setObjectName("selectedParameter")
        self._selected_parameter.setWordWrap(True)
        editor_layout.addWidget(self._selected_parameter)

        self._parameter_details = QLabel(
            "Choose a row to inspect its value and available controls."
        )
        self._parameter_details.setObjectName("parameterDetails")
        self._parameter_details.setWordWrap(True)
        editor_layout.addWidget(self._parameter_details)

        self._editor_pages = QStackedWidget()
        self._editor_pages.setObjectName("parameterEditorPages")
        self._editor_pages.addWidget(self._build_empty_editor())
        self._editor_pages.addWidget(self._build_adc_selector_editor())
        self._editor_pages.addWidget(self._build_source_selector_editor())
        self._editor_pages.addWidget(self._build_compressor_editor())
        self._editor_pages.addWidget(self._build_gain_editor())
        self._editor_pages.addWidget(self._build_raw_editor())
        editor_layout.addWidget(self._editor_pages, 1)
        self._raw_editor = self._build_hex_editor("Raw parameter bytes")
        editor_layout.addWidget(self._raw_editor)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._read_button = QPushButton("Read")
        self._read_button.setObjectName("readParameterButton")
        actions.addWidget(self._read_button, 1)
        self._write_button = QPushButton("Persist value")
        self._write_button.setObjectName("writeParameterButton")
        actions.addWidget(self._write_button, 1)
        editor_layout.addLayout(actions)
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 350])
        layout.addWidget(splitter, 1)

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

    @staticmethod
    def _build_empty_editor() -> QWidget:
        """Build the inspector placeholder shown without a selection."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        prompt = QLabel("Select a parameter from the table.")
        prompt.setObjectName("parameterEditorPrompt")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)
        layout.addStretch()
        return page

    def _build_adc_selector_editor(self) -> QWidget:
        """Build four radio controls for the ADC input selector."""
        return self._build_selector_editor(
            DspParameterId.ADC_SELECT,
            "ADC input",
            ((0, "ADC 0"), (1, "ADC 1"), (2, "ADC 2"), (3, "ADC 3")),
        )

    def _build_source_selector_editor(self) -> QWidget:
        """Build radio controls for digital-versus-ADC source selection."""
        return self._build_selector_editor(
            DspParameterId.SOURCE_SELECT,
            "Processing source",
            ((0, "Digital input (I2S)"), (1, "Selected ADC input")),
        )

    def _build_selector_editor(
        self,
        parameter_id: DspParameterId,
        heading: str,
        choices: tuple[tuple[int, str], ...],
    ) -> QWidget:
        """Build one typed selector page backed by an exclusive button group.

        Args:
            parameter_id: Stable selector parameter identifier.
            heading: Human-readable control group heading.
            choices: Numeric values and labels accepted by the DSP switch.

        Returns:
            Page containing the radio-button choices.
        """
        if not hasattr(self, "_selector_groups"):
            self._selector_groups: dict[int, QButtonGroup] = {}
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(9)
        label = QLabel(heading)
        label.setProperty("role", "fieldLabel")
        layout.addWidget(label)
        group = QButtonGroup(page)
        group.setExclusive(True)
        for value, text in choices:
            button = QRadioButton(text)
            button.setObjectName(f"parameterSelector{int(parameter_id)}Value{value}")
            button.setAccessibleDescription(
                f"Write unsigned 32-bit selector value {value}"
            )
            group.addButton(button, value)
            layout.addWidget(button)
        self._selector_groups[int(parameter_id)] = group
        layout.addStretch()
        return page

    def _build_compressor_editor(self) -> QWidget:
        """Build the decoded curve and raw-byte editor for compressor LUTs."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(7)
        self._curve_summary = QLabel("Read this parameter to display its curve.")
        self._curve_summary.setObjectName("compressorCurveSummary")
        self._curve_summary.setWordWrap(True)
        layout.addWidget(self._curve_summary)
        self._compressor_curve = CompressorCurveWidget()
        layout.addWidget(self._compressor_curve, 1)
        return page

    def _build_gain_editor(self) -> QWidget:
        """Build numerical linear and decibel displays for one gain word."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 16, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self._gain_linear_value = QLabel("—")
        self._gain_linear_value.setObjectName("gainLinearValue")
        self._gain_linear_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        linear_label = QLabel("Linear gain")
        linear_label.setProperty("role", "fieldLabel")
        form.addRow(linear_label, self._gain_linear_value)

        self._gain_db_value = QLabel("—")
        self._gain_db_value.setObjectName("gainDecibelValue")
        self._gain_db_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        db_label = QLabel("Gain in dB")
        db_label.setProperty("role", "fieldLabel")
        form.addRow(db_label, self._gain_db_value)
        return page

    def _build_raw_editor(self) -> QWidget:
        """Build the fallback hexadecimal editor for untyped parameters."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        note = QLabel(
            "This parameter has no specialized control. Edit its complete "
            "byte array in hexadecimal below."
        )
        note.setObjectName("rawParameterHelp")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_hex_editor(self, heading: str) -> QWidget:
        """Build the raw-byte input shared by typed parameter views.

        Args:
            heading: Label displayed above the input on its owning page.

        Returns:
            Container owning the application-wide parameter byte input.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(heading)
        label.setProperty("role", "fieldLabel")
        layout.addWidget(label)
        self._value_input = QLineEdit()
        self._value_input.setObjectName("parameterValueInput")
        self._value_input.setPlaceholderText("Hex bytes, for example: 00 00 00 01")
        self._value_input.setAccessibleName("Parameter value in hexadecimal bytes")
        self._value_input.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        layout.addWidget(self._value_input)
        return container

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
            self._parameter_details.setText(
                "Choose a row to inspect its value and available controls."
            )
            self._editor_pages.setCurrentIndex(_EDITOR_EMPTY)
            self._value_input.clear()
        else:
            block = DSP_BLOCKS_BY_ID[definition.block_id]
            self._selected_parameter.setText(
                f"#{definition.parameter_id} · {block.name} · {definition.name}"
            )
            access = (
                "Read, write, and persist" if definition.writable else "Read only"
            )
            if self._is_selector(definition):
                value_type = "Unsigned 32-bit selector"
                self._editor_pages.setCurrentIndex(
                    _EDITOR_ADC_SELECT
                    if definition.parameter_id == DspParameterId.ADC_SELECT
                    else _EDITOR_SOURCE_SELECT
                )
            elif self._is_compressor(definition):
                value_type = "34 SigmaDSP 5.23 words"
                self._editor_pages.setCurrentIndex(_EDITOR_COMPRESSOR)
            elif self._is_gain(definition):
                value_type = "One SigmaDSP 5.23 linear-gain word"
                self._editor_pages.setCurrentIndex(_EDITOR_GAIN)
            else:
                value_type = "Opaque byte array"
                self._editor_pages.setCurrentIndex(_EDITOR_RAW)
            self._parameter_details.setText(
                f"{definition.byte_count} bytes · {access} · {value_type}"
            )
            self._render_selected_value(
                definition, self._stored_values.get(definition.parameter_id)
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
        """Encode the active editor and persist fixed-contract bytes."""
        definition = self._selected_definition()
        if definition is None:
            return
        if self._is_selector(definition):
            group = self._selector_groups[int(definition.parameter_id)]
            selected_value = group.checkedId()
            if selected_value < 0:
                self._show_message("Select one of the available switch values.", True)
                return
            data = encode_u32_word(selected_value)
        else:
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
        """Update the table and selected presentation-only value editor."""
        self._stored_values[value.parameter_id] = value
        definition = self._definitions.get(value.parameter_id)
        if definition is None:
            return
        for row in range(self._parameter_table.rowCount()):
            item = self._parameter_table.item(row, 0)
            if (
                item is not None
                and item.data(Qt.ItemDataRole.UserRole) == value.parameter_id
            ):
                encoded = value.data.hex(" ").upper()
                if len(value.data) <= 8:
                    displayed = encoded
                else:
                    displayed = (
                        f"{len(value.data)} bytes · {encoded[:23]} … "
                        f"{encoded[-23:]}"
                    )
                value_item = self._parameter_table.item(row, 5)
                value_item.setText(displayed)
                value_item.setToolTip(encoded)
                if self._parameter_table.currentRow() == row:
                    self._render_selected_value(definition, value)
                break

    def _render_selected_value(
        self,
        definition: DspParameterDefinition,
        value: ParameterValue | None,
    ) -> None:
        """Populate the specialized editor from an unchanged byte payload.

        Args:
            definition: Metadata for the selected parameter.
            value: Most recently read or written bytes, if available.
        """
        if value is None:
            self._value_input.clear()
            if self._is_selector(definition):
                self._clear_selector(definition.parameter_id)
            elif self._is_compressor(definition):
                self._compressor_curve.set_values(())
                self._curve_summary.setText(
                    "Read this parameter to display its curve."
                )
            elif self._is_gain(definition):
                self._gain_linear_value.setText("—")
                self._gain_db_value.setText("—")
            return

        encoded = value.data.hex(" ").upper()
        self._value_input.setText(encoded)
        if self._is_selector(definition):
            selected_value = decode_u32_word(value.data)
            group = self._selector_groups[int(definition.parameter_id)]
            button = group.button(selected_value)
            if button is None:
                self._clear_selector(definition.parameter_id)
                self._parameter_details.setText(
                    f"{definition.byte_count} bytes · Unsupported stored selector "
                    f"value {selected_value}"
                )
            else:
                button.setChecked(True)
            return

        if self._is_compressor(definition):
            values = decode_sigma_5_23_words(value.data)
            self._compressor_curve.set_values(values)
            outputs = tuple(
                output_level
                for _input_level, output_level in self._compressor_curve.points_dbfs
            )
            self._curve_summary.setText(
                f"{len(values)} points · input −90 to +6 dBFS · output "
                f"{min(outputs):.1f} to {max(outputs):.1f} dBFS"
            )
            return

        if self._is_gain(definition):
            linear_gain = decode_sigma_5_23_words(value.data)[0]
            linear_text, db_text = self._format_gain(linear_gain)
            self._gain_linear_value.setText(linear_text)
            self._gain_db_value.setText(db_text)

    def _clear_selector(self, parameter_id: int) -> None:
        """Clear a radio group so missing or invalid bytes are not misrepresented."""
        group = self._selector_groups[int(parameter_id)]
        group.setExclusive(False)
        for button in group.buttons():
            button.setChecked(False)
        group.setExclusive(True)

    @staticmethod
    def _is_selector(definition: DspParameterDefinition) -> bool:
        """Return whether a parameter uses one of the typed switch editors."""
        return definition.parameter_id in (
            DspParameterId.ADC_SELECT,
            DspParameterId.SOURCE_SELECT,
        )

    @staticmethod
    def _is_compressor(definition: DspParameterDefinition) -> bool:
        """Return whether a parameter is one of the eight compressor LUTs."""
        return int(definition.parameter_id) in _COMPRESSOR_PARAMETER_IDS

    @staticmethod
    def _is_gain(definition: DspParameterDefinition) -> bool:
        """Return whether a parameter is a phase-compensation or headroom gain."""
        return int(definition.parameter_id) in _GAIN_PARAMETER_IDS

    @staticmethod
    def _format_gain(linear_gain: float) -> tuple[str, str]:
        """Format a dimensionless linear gain and its decibel equivalent.

        Args:
            linear_gain: Value decoded from one SigmaDSP 5.23 word.

        Returns:
            Display strings for linear and decibel gain. Zero linear gain is
            represented as negative infinity dB; negative gain has no real dB
            equivalent and is reported explicitly.
        """
        linear_text = f"{linear_gain:.8g}"
        if linear_gain > 0.0:
            return linear_text, f"{20.0 * log10(linear_gain):.2f} dB"
        if linear_gain == 0.0:
            return linear_text, "−∞ dB"
        return linear_text, "Undefined for negative gain"

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
        for parameter_id, group in self._selector_groups.items():
            selected_group = bool(
                idle
                and definition
                and int(definition.parameter_id) == parameter_id
            )
            for button in group.buttons():
                button.setEnabled(selected_group)
        show_raw = bool(
            definition
            and definition.writable
            and not self._is_selector(definition)
        )
        self._raw_editor.setVisible(show_raw)
        self._value_input.setEnabled(self._write_button.isEnabled())
        self._refresh_button.setEnabled(idle)

    def _show_message(self, text: str, error: bool = False) -> None:
        """Render a contextual parameter-operation message."""
        self._message.setText(text)
        self._message.setProperty("error", error)
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
