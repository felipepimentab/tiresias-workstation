"""Edit the five fitting libraries and load board-ready objects through BLE.

Generation and DSP compilation run on a worker. Widgets only collect inputs,
render immutable results and delegate persistence to the application service.
"""

from dataclasses import replace
import json
import math

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QProgressBar, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from tiresias_workstation.adapters.library_store import entry_to_dict
from tiresias_workstation.application.fitting_library import FittingLibrary
from tiresias_workstation.domain.fittings import Audiogram
from tiresias_workstation.domain.dsp_contract import DSP_PARAMETERS_BY_ID
from tiresias_workstation.domain.library import (
    LIBRARY_KINDS, CalibrationBand, DeviceCalibration, LibraryEntry, OutputStageConfiguration,
)

LABELS = ("Audiograms", "Prescription targets", "Detector calibrations", "Compiled DSP objects", "Output-stage calibration")
PAGE_LABELS = dict(zip(LIBRARY_KINDS, LABELS))
PAGE_DESCRIPTIONS = {
    "audiograms": "Hearing thresholds for both ears. Use these local records to generate prescription targets.",
    "targets": "Desired acoustic gains generated from an audiogram and a prescriptive rule. Compile a target with detector calibration to create board values.",
    "calibrations": "Measured detector-to-acoustic-level mappings. These local records are inputs to DSP compilation.",
    "compiled": "Compressor LUTs and bias gains compiled from a target, detector calibration and selected ear. These values can be loaded to the board.",
    "outputs": "Output headroom and the SoftClip curve. These values can be loaded to the board separately from a compiled DSP object.",
}
SINGULAR = dict(zip(LIBRARY_KINDS, ("audiogram", "prescription target", "detector calibration", "compiled DSP prescription", "output-stage configuration")))


class _Signals(QObject):
    """Deliver worker outcomes to the owning dialog's UI thread.

    Signals:
        completed(object): Immutable generated value.
        failed(str): Generation error suitable for display.
    """

    completed = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    """Run one captured generation operation without touching widgets."""

    def __init__(self, operation) -> None:
        """Retain the operation and signal owner until completion."""
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        """Publish exactly one terminal generation result."""
        try:
            self.signals.completed.emit(self.operation())
        except Exception as error:
            self.signals.failed.emit(str(error))


def _table(headers, rows) -> QTableWidget:
    """Create an editable numeric table with explicit units in its headers."""
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            table.setItem(row_index, column, QTableWidgetItem(str(value)))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def _rows(table: QTableWidget) -> list[list[str]]:
    """Read every cell, rejecting missing values rather than filling silently."""
    rows = []
    for row in range(table.rowCount()):
        values = []
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is None or not item.text().strip():
                raise ValueError(f"Complete row {row + 1}, column {column + 1}.")
            values.append(item.text().strip())
        rows.append(values)
    return rows


class LibraryEditor(QDialog):
    """Create, inspect or update one kind-specific library object."""

    def __init__(self, library: FittingLibrary, kind: str, entry: LibraryEntry | None = None,
                 parent=None, *, view_only: bool = False) -> None:
        """Build a typed editor using immutable source snapshots."""
        super().__init__(parent)
        self.library, self.kind, self.entry = library, kind, entry
        self.read_only = view_only or bool(entry and entry.read_only)
        self.value = entry.value if entry else None
        self.sources = entry.sources if entry else ()
        self.saved_entry = None
        self._task = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self.setWindowTitle(("View " if self.read_only else "Edit " if entry else "New ") + SINGULAR[kind])
        self.resize(880, 660)
        root = QVBoxLayout(self)
        self.form = QFormLayout()
        self.name = QLineEdit(entry.name if entry else "")
        self.name.setPlaceholderText(f"Name this {SINGULAR[kind]}")
        self.form.addRow("Name", self.name)
        root.addLayout(self.form)
        self.body = QVBoxLayout()
        root.addLayout(self.body, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        builders = {"audiograms": self._audiogram, "targets": self._target,
                    "calibrations": self._calibration, "compiled": self._compiled, "outputs": self._output}
        builders[kind]()
        if self.read_only:
            self.name.setReadOnly(True)
            for child in self.findChildren(QLineEdit):
                child.setReadOnly(True)
            for table in self.findChildren(QTableWidget):
                table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for child in self.findChildren(QDoubleSpinBox):
                child.setEnabled(False)
            for child in self.findChildren(QComboBox):
                child.setEnabled(False)
            for child in self.findChildren(QPushButton):
                if child is not self.buttons.button(QDialogButtonBox.StandardButton.Cancel):
                    child.setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).hide()
            self.message.setText("Read-only reference. Duplicate it to make a custom version." if entry and entry.read_only else "Saved generation snapshot.")

    def _source_combo(self, kind: str, label: str) -> QComboBox:
        """Populate dependencies by stable ID and restore an existing reference."""
        combo = QComboBox()
        for entry in self.library.list(kind):
            combo.addItem(entry.name, entry.item_id)
        source = next((source for source in self.sources if source.kind == kind), None)
        if source:
            combo.setCurrentIndex(combo.findData(source.item_id))
        self.form.addRow(label, combo)
        return combo

    def _row_controls(self, table: QTableWidget) -> None:
        """Allow custom audiometric frequencies and calibration checkpoints."""
        layout = QHBoxLayout()
        add, remove = QPushButton("Add row"), QPushButton("Remove selected row")
        add.clicked.connect(lambda: table.insertRow(table.rowCount()))
        remove.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
        layout.addWidget(add)
        layout.addWidget(remove)
        layout.addStretch()
        self.body.addLayout(layout)

    def _audiogram(self) -> None:
        """Present frequencies and separate left/right dB HL thresholds."""
        value = self.value or Audiogram((250., 500., 1000., 2000., 4000., 6000.), (0.,) * 6, (0.,) * 6)
        self.audio_table = _table(("Frequency (Hz)", "Left (dB HL)", "Right (dB HL)"),
                                 list(zip(value.frequencies_hz, value.left_levels_db_hl, value.right_levels_db_hl)))
        self.body.addWidget(self.audio_table)
        self._row_controls(self.audio_table)

    def _target(self) -> None:
        """Separate portable target generation from calibration and compilation."""
        self.audio = self._source_combo("audiograms", "Source audiogram")
        self.rule = QComboBox()
        for rule in self.library.rules.values():
            self.rule.addItem(rule.metadata.display_name, rule.metadata.rule_id)
        if self.value:
            self.rule.setCurrentIndex(self.rule.findData(self.value.rule.rule_id))
        self.form.addRow("Prescriptive rule", self.rule)
        self.generate_button = QPushButton("Generate target from audiogram")
        self.generate_button.clicked.connect(self._generate_target)
        self.body.addWidget(self.generate_button)
        self.target_tabs = QTabWidget()
        self.body.addWidget(self.target_tabs, 1)
        self.rule_description = QLabel()
        self.rule_description.setWordWrap(True)
        self.body.addWidget(self.rule_description)
        if self.value:
            self._show_target()
        for combo in (self.audio, self.rule):
            combo.currentIndexChanged.connect(self._invalidate_generation)

    def _show_target(self) -> None:
        """Render both gain matrices with acoustic input axes and rule provenance."""
        self.target_tabs.clear()
        self.gain_tables = []
        for ear in ("left", "right"):
            table = _table([f"{v:g} dB SPL" for v in self.value.input_levels_db_spl], self.value.gains(ear))
            table.setVerticalHeaderLabels([f"{v:g} Hz" for v in self.value.band_centres_hz])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            table.horizontalHeader().setDefaultSectionSize(95)
            self.target_tabs.addTab(table, f"{ear.title()} gain (dB)")
            self.gain_tables.append(table)
        rule = self.value.rule
        self.rule_description.setText(f"{rule.display_name} · version {rule.version}\n{rule.source}\n{self.value.endpoint_policy}")

    def _calibration(self) -> None:
        """Expose measured band checkpoints and endpoint policy without DSP addresses."""
        value = self.value or self.library.get("calibrations", "eval-detector").value
        self.calibration_id = QLineEdit(value.calibration_id if self.entry else "custom-detector")
        self.scope = QLineEdit(value.scope)
        self.convention = QLineEdit(value.detector_convention)
        self.provenance = QLineEdit(value.provenance)
        for label, field in (("Calibration ID", self.calibration_id), ("Measurement scope", self.scope),
                             ("Detector convention", self.convention), ("Provenance / notes", self.provenance)):
            self.form.addRow(label, field)
        rows = [(i, band.frequency_hz, detector, spl, "hold" if band.hold_low else "extrapolate")
                for i, band in enumerate(value.bands, 1)
                for detector, spl in zip(band.detector_dbfs, band.equivalent_input_db_spl)]
        self.calibration_table = _table(("Band (1–8)", "Test Hz", "RMS detector dBFS", "Equivalent dB SPL", "Low endpoint"), rows)
        self.body.addWidget(self.calibration_table)
        self._row_controls(self.calibration_table)
        self.body.addWidget(QLabel("Low endpoint: hold or extrapolate. High endpoint: linear extrapolation."))

    def _compiled(self) -> None:
        """Select separately stored target, calibration and monaural ear."""
        self.target = self._source_combo("targets", "Prescription target")
        self.calibration = self._source_combo("calibrations", "Detector calibration")
        self.ear = QComboBox()
        self.ear.addItems(("left", "right"))
        if self.value:
            self.ear.setCurrentText(self.value.artifact.mapping.ear)
        self.form.addRow("Ear for the board", self.ear)
        self.generate_button = QPushButton("Compile DSP prescription")
        self.generate_button.clicked.connect(self._compile)
        if self.target.count() == 0:
            self.generate_button.setEnabled(False)
            self.message.setText("Create a saved prescription target before compiling.")
        self.body.addWidget(self.generate_button)
        self.compiled_preview = QPlainTextEdit()
        self.compiled_preview.setReadOnly(True)
        self.body.addWidget(self.compiled_preview)
        if self.value:
            self._show_compiled()
        for combo in (self.target, self.calibration, self.ear):
            combo.currentIndexChanged.connect(self._invalidate_generation)

    def _show_compiled(self) -> None:
        """Show the actual compiled bytes and the immutable calibration identity."""
        artifact = self.value.artifact
        lines = [f"Compiler: {self.value.compiler_version}", f"Calibration: {self.value.calibration.calibration_id}",
                 f"Ear: {artifact.mapping.ear}", "8 compressor LUTs + 3 bias gains · 1,100 bytes", ""]
        for parameter in artifact.prescription.parameters:
            lines.append(f"Parameter {int(parameter.parameter_id)} ({len(parameter.data)} bytes)\n{parameter.data.hex()}\n")
        self.compiled_preview.setPlainText("\n".join(lines))

    def _output(self) -> None:
        """Edit nominal output reference and peak-limiting settings coherently."""
        value = self.value or self.library.get("outputs", "eval-output").value
        self.output_fields = {}
        for key, label, minimum, maximum in (
            ("headroom_db", "Headroom gain (dB)", -100, 24),
            ("threshold_dbfs_peak", "SoftClip threshold (dBFS peak)", -90, 0),
            ("compression_ratio", "Compression ratio", 1, 100),
            ("ceiling_dbfs_peak", "Output ceiling (dBFS peak)", -89.9, 0),
        ):
            field = QDoubleSpinBox()
            field.setDecimals(4)
            field.setRange(minimum, maximum)
            field.setValue(getattr(value, key))
            self.output_fields[key] = field
            self.form.addRow(label, field)
        self.output_provenance = QLineEdit(value.provenance)
        self.form.addRow("Provenance / notes", self.output_provenance)
        note = QLabel("Loads Headroom and the complete 45-word nominal SoftClip LUT.\n"
                      "Requires the program's fixed hold 0x00000000 and decay 0x0000013D; these are not transferred.\n"
                      "The two parameters load sequentially. Detector calibration is independent of this output stage.")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self.body.addStretch()

    @Slot()
    def _invalidate_generation(self) -> None:
        """Require regeneration after a dependency selection changes."""
        self.value = None
        self.message.setText("Generate again to use the selected inputs.")

    def _start(self, operation) -> None:
        """Disable mutable inputs while captured generation runs off the UI thread."""
        if self._task is not None:
            return
        self._task = _Task(operation)
        self._task.signals.completed.connect(self._generated)
        self._task.signals.failed.connect(self._failed)
        self.buttons.setEnabled(False)
        self.generate_button.setEnabled(False)
        for combo in self.findChildren(QComboBox):
            combo.setEnabled(False)
        self.message.setText("Generating…")
        self._pool.start(self._task)

    @Slot()
    def _generate_target(self) -> None:
        """Capture the source audiogram and selected rule before dispatch."""
        try:
            audio = self.library.get("audiograms", self.audio.currentData())
            rule_id = self.rule.currentData()
            self.sources = (self.library.reference(audio),)
            self._start(lambda: self.library.generate_target(audio, rule_id))
        except Exception as error:
            self.message.setText(str(error))

    @Slot()
    def _compile(self) -> None:
        """Capture both compilation dependencies and the selected ear."""
        try:
            target = self.library.get("targets", self.target.currentData())
            calibration = self.library.get("calibrations", self.calibration.currentData())
            name, ear = self.name.text().strip(), self.ear.currentText()
            if not name:
                raise ValueError("Name the compiled prescription first.")
            self.sources = (self.library.reference(target), self.library.reference(calibration))
            self._start(lambda: self.library.compile(target, calibration, ear, name))
        except Exception as error:
            self.message.setText(str(error))

    @Slot(object)
    def _generated(self, value) -> None:
        """Render a generated immutable value on the GUI thread."""
        self.value = value
        self._finish_task()
        if self.kind == "targets":
            self._show_target()
        else:
            self._show_compiled()
        self.message.setText("Generated. Save to add this object to the library.")

    @Slot(str)
    def _failed(self, message: str) -> None:
        """Release the worker slot and show a recoverable generation error."""
        self._finish_task()
        self.message.setText(message)

    def _finish_task(self) -> None:
        """Restore editor controls after the worker's terminal signal."""
        self._task = None
        self.buttons.setEnabled(True)
        self.generate_button.setEnabled(True)
        for combo in self.findChildren(QComboBox):
            combo.setEnabled(True)

    def reject(self) -> None:
        """Keep the worker's owner alive until generation finishes."""
        if self._task is None:
            super().reject()

    def _edited_value(self):
        """Parse typed editor inputs and let domain constructors validate them."""
        if self.kind == "audiograms":
            rows = [[float(value) for value in row] for row in _rows(self.audio_table)]
            if not rows:
                raise ValueError("Enter an audiogram first.")
            return Audiogram(*(tuple(row[i] for row in rows) for i in range(3)))
        if self.kind == "targets":
            if self.value is None:
                raise ValueError("Generate a target first.")
            matrices = [tuple(tuple(float(cell) for cell in row) for row in _rows(table)) for table in self.gain_tables]
            return replace(self.value, left_gain_db_by_band=matrices[0], right_gain_db_by_band=matrices[1])
        if self.kind == "calibrations":
            groups = {i: [] for i in range(1, 9)}
            for row in _rows(self.calibration_table):
                band = int(row[0])
                if band not in groups or row[4] not in ("hold", "extrapolate"):
                    raise ValueError("Use band 1–8 and endpoint hold or extrapolate.")
                groups[band].append(row)
            bands = []
            for rows in groups.values():
                if not rows or len({(row[1], row[4]) for row in rows}) != 1:
                    raise ValueError("Every band needs checkpoints with one frequency and endpoint policy.")
                bands.append(CalibrationBand(float(rows[0][1]), tuple(float(r[2]) for r in rows),
                                             tuple(float(r[3]) for r in rows), rows[0][4] == "hold"))
            return DeviceCalibration(self.calibration_id.text(), self.scope.text(), self.convention.text(),
                                     tuple(bands), self.provenance.text())
        if self.kind == "outputs":
            return OutputStageConfiguration(**{key: field.value() for key, field in self.output_fields.items()},
                                            provenance=self.output_provenance.text())
        if self.value is None:
            raise ValueError("Compile a DSP prescription first.")
        return self.value

    @Slot()
    def _save(self) -> None:
        """Commit one fully validated user object and keep errors in the editor."""
        if self.read_only or self._task is not None:
            return
        try:
            value = self._edited_value()
            provenance = self.entry.provenance if self.entry else "User-created"
            if self.kind == "targets" and value != self.value:
                provenance = "User-edited gain target based on " + value.rule.display_name
            self.saved_entry = self.library.save(self.kind, self.name.text(), value,
                item_id=self.entry.item_id if self.entry else None, sources=self.sources, provenance=provenance)
        except Exception as error:
            self.message.setText(str(error))
            return
        self.accept()


class FittingLibraryScreen(QWidget):
    """Manage one data object type, with transfer controls only for board values.

    Signals:
        changed(): A saved object was created, edited or deleted.
    """

    changed = Signal()

    def __init__(self, library: FittingLibrary, controller, parent=None, *, kind: str = "audiograms") -> None:
        """Build a dedicated object page.

        Args:
            library: Shared persistent object library.
            controller: Shared BLE controller; only board pages observe transfers.
            parent: Optional owning widget.
            kind: Fixed object kind for this page's entire lifetime.
        """
        super().__init__(parent)
        if kind not in LIBRARY_KINDS:
            raise ValueError("Unknown object page kind.")
        self._kind = kind
        self.board_loadable = kind in ("compiled", "outputs")
        self.library, self.controller = library, controller
        self._connected = False
        self._loading_id = None
        self._owns_transfer = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        role = QLabel("BOARD-LOADABLE VALUES" if self.board_loadable else "LOCAL REFERENCE & DESIGN DATA")
        role.setObjectName("boardObjectRole" if self.board_loadable else "referenceObjectRole")
        root.addWidget(role)
        title = QLabel(PAGE_LABELS[kind])
        title.setObjectName("pageTitle")
        root.addWidget(title)
        explanation = QLabel(PAGE_DESCRIPTIONS[kind])
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        splitter = QSplitter()
        self.items = QListWidget()
        self.items.setMinimumWidth(210)
        self.items.setSpacing(4)
        splitter.addWidget(self.items)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self.summary)
        inspection = QTabWidget()
        self.values = QTableWidget()
        self.values.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.values.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        inspection.addTab(self.values, "Values")
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        inspection.addTab(self.details, "JSON / provenance")
        detail_layout.addWidget(inspection)
        splitter.addWidget(detail)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        row = QHBoxLayout()
        self.new_button = QPushButton("Compile new" if kind == "compiled" else "Generate new" if kind == "targets" else "New")
        self.view_button = QPushButton("View")
        self.edit_button = QPushButton("Edit")
        self.copy_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        for button in (self.new_button, self.view_button, self.edit_button, self.copy_button, self.delete_button):
            row.addWidget(button)
        row.addStretch()
        root.addLayout(row)
        self.load_button = None
        self.transfer_panel = None
        self.status = QLabel("Reference objects are fixed; duplicate them to create custom versions.")
        self.status.setWordWrap(True)
        if self.board_loadable:
            self.transfer_panel = QFrame()
            self.transfer_panel.setObjectName("boardTransferCard")
            transfer = QVBoxLayout(self.transfer_panel)
            transfer.setContentsMargins(14, 12, 14, 12)
            heading = QHBoxLayout()
            heading.addWidget(QLabel("BOARD TRANSFER"))
            heading.addStretch()
            self.load_button = QPushButton("Load selected values to board")
            self.load_button.setObjectName("loadObjectToBoardButton")
            self.load_button.clicked.connect(self._load)
            heading.addWidget(self.load_button)
            transfer.addLayout(heading)
            self.transfer_summary = QLabel()
            self.transfer_summary.setWordWrap(True)
            transfer.addWidget(self.transfer_summary)
            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setVisible(False)
            transfer.addWidget(self.progress)
            self.status.setText("Connect a compatible board to load the selected values.")
            transfer.addWidget(self.status)
            root.addWidget(self.transfer_panel)
        else:
            root.addWidget(self.status)
        self.items.currentItemChanged.connect(self._selected)
        self.items.itemDoubleClicked.connect(lambda *_: self._edit(view=True))
        self.new_button.clicked.connect(lambda: self._edit(new=True))
        self.view_button.clicked.connect(lambda: self._edit(view=True))
        self.edit_button.clicked.connect(self._edit)
        self.copy_button.clicked.connect(self._copy)
        self.delete_button.clicked.connect(self._delete)
        if self.board_loadable:
            controller.session_loaded.connect(self._session)
            controller.disconnected.connect(self._disconnected)
            controller.prescription_load_started.connect(self._load_started)
            controller.prescription_load_progress.connect(self._load_progress)
            controller.prescription_loaded.connect(self._loaded)
            controller.prescription_load_failed.connect(self._load_failed)
        self.toast = QLabel(self)
        self.toast.setObjectName("libraryToast")
        self.toast.setTextFormat(Qt.TextFormat.PlainText)
        self.toast.setWordWrap(True)
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(8000)
        self._toast_timer.timeout.connect(self.toast.hide)
        self.refresh()

    def _show_toast(self, message: str) -> None:
        """Show nonmodal feedback, restarting its lifetime for repeated actions."""
        self.toast.setText(message)
        self._position_toast()
        self.toast.show()
        self.toast.raise_()
        self._toast_timer.start()

    def _position_toast(self) -> None:
        """Keep wrapped feedback inside the page when the window is resized."""
        width = max(1, min(560, self.width() - 48))
        self.toast.setFixedWidth(width)
        self.toast.adjustSize()
        self.toast.move((self.width() - width) // 2,
                        max(20, self.height() - self.toast.height() - 24))

    def resizeEvent(self, event) -> None:
        """Reposition the transient overlay without changing the page layout."""
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self._position_toast()

    @property
    def kind(self) -> str:
        """Return this page's fixed object category."""
        return self._kind

    def selected_entry(self) -> LibraryEntry | None:
        """Resolve selection against storage rather than a stale display copy."""
        item = self.items.currentItem()
        return self.library.get(self.kind, item.data(Qt.ItemDataRole.UserRole)) if item else None

    @Slot()
    def refresh(self, *_args, select_id: str | None = None) -> None:
        """Refresh lists after edits, preserving selection when possible."""
        current = self.items.currentItem()
        selected = select_id or (current.data(Qt.ItemDataRole.UserRole) if current else None)
        self.items.clear()
        for entry in self.library.list(self.kind):
            item = QListWidgetItem(entry.name + ("  · Reference" if entry.read_only else ""))
            item.setData(Qt.ItemDataRole.UserRole, entry.item_id)
            self.items.addItem(item)
            if entry.item_id == selected:
                self.items.setCurrentItem(item)
        if self.items.currentRow() < 0 and self.items.count():
            self.items.setCurrentRow(0)
        self._selected()

    @Slot()
    def _selected(self, *_args) -> None:
        """Show object identity, dependencies and inspectable data."""
        entry = self.selected_entry()
        for button in (self.view_button, self.copy_button):
            button.setEnabled(entry is not None)
        for button in (self.edit_button, self.delete_button):
            button.setEnabled(entry is not None and not entry.read_only)
        if self.load_button is not None:
            self.load_button.setEnabled(bool(entry and self._connected and not self._loading_id))
            if entry is None:
                self.transfer_summary.setText("Create or select an object to see its board payload.")
            else:
                payload = "11 parameters · 1,100 bytes · compressor LUTs + bias gains" if self.kind == "compiled" else "2 parameters · 184 bytes · Headroom + SoftClip"
                self.transfer_summary.setText(f"Selected: {entry.name}\n{payload}")
        if entry is None:
            self.summary.setText("No saved objects yet. Choose New to create one.")
            self.details.clear()
            self.values.setRowCount(0)
            return
        text = f"{entry.name}\n{'Read-only reference' if entry.read_only else 'Custom object'} · revision {entry.revision}\n{entry.provenance}"
        for source in entry.sources:
            try:
                source_name = self.library.get(source.kind, source.item_id).name
            except KeyError:
                source_name = source.item_id
            text += f"\nSource {SINGULAR[source.kind]}: {source_name}"
        changes = self.library.changed_sources(entry)
        if changes:
            text += "\nSource changed since generation: " + ", ".join(changes) + ". Saved values remain unchanged."
        if entry.kind == "targets":
            text += f"\nRule: {entry.value.rule.display_name} · {entry.value.rule.version}"
        if entry.kind == "compiled":
            text += f"\n{entry.value.artifact.mapping.ear.title()} ear · 11 parameters · 1,100 bytes"
        if entry.kind == "outputs":
            text += f"\nHeadroom {entry.value.headroom_db:g} dB · 2 parameters · 184 bytes"
        self.summary.setText(text)
        self.details.setPlainText(json.dumps(entry_to_dict(entry), indent=2, ensure_ascii=False))
        self._preview_values(entry)

    def _preview_values(self, entry: LibraryEntry) -> None:
        """Present engineering units directly, leaving serialization in a second tab."""
        value = entry.value
        if entry.kind == "audiograms":
            headers = ("Frequency (Hz)", "Left (dB HL)", "Right (dB HL)")
            rows = list(zip(value.frequencies_hz, value.left_levels_db_hl, value.right_levels_db_hl))
        elif entry.kind == "targets":
            headers = ("Band (Hz)", "Left gain @45 dB SPL", "Left @65", "Left @85", "Right @45", "Right @65", "Right @85")
            rows = [(frequency, *(round(value.gain_at(ear, index, level), 2)
                                  for ear in ("left", "right") for level in (45, 65, 85)))
                    for index, frequency in enumerate(value.band_centres_hz)]
            self.summary.setText(self.summary.text() + "\nPreview gains are dB; View shows both complete target matrices.")
        elif entry.kind == "calibrations":
            headers = ("Band", "Test Hz", "RMS detector dBFS", "Equivalent dB SPL", "Low endpoint")
            rows = [(index, band.frequency_hz, detector, spl, "Hold" if band.hold_low else "Extrapolate")
                    for index, band in enumerate(value.bands, 1)
                    for detector, spl in zip(band.detector_dbfs, band.equivalent_input_db_spl)]
        elif entry.kind == "compiled":
            headers = ("Parameter", "Value bytes", "5.23 words")
            rows = [(f"{int(parameter.parameter_id)} · {DSP_PARAMETERS_BY_ID[parameter.parameter_id].name}",
                     len(parameter.data), len(parameter.data) // 4)
                    for parameter in value.artifact.prescription.parameters]
        else:
            headers = ("Input (dBFS peak)", "SoftClip gain (dB)", "Output (dBFS peak)")
            data = value.parameters()[1].data
            gains = [20 * math.log10(int.from_bytes(data[i:i + 4], "big") / (1 << 23))
                     for i in range(0, len(data), 4)]
            rows = [("Underflow" if index == 0 else -90 + (index - 1) * 3, round(gain, 3),
                     "—" if index == 0 else round(-90 + (index - 1) * 3 + gain, 3))
                    for index, gain in enumerate(gains)]
        self.values.setColumnCount(len(headers))
        self.values.setHorizontalHeaderLabels(headers)
        self.values.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                self.values.setItem(row_index, column, QTableWidgetItem(f"{value:g}" if isinstance(value, float) else str(value)))

    def _edit(self, _checked=False, *, new=False, view=False) -> None:
        """Open a typed editor and publish successful persistence."""
        entry = None if new else self.selected_entry()
        if not new and entry is None:
            return
        dialog = LibraryEditor(self.library, self.kind, entry, self, view_only=view)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(select_id=dialog.saved_entry.item_id)
            self.changed.emit()

    @Slot()
    def _copy(self) -> None:
        """Duplicate references or custom objects into an editable new object."""
        try:
            entry = self.selected_entry()
            if entry:
                copied = self.library.duplicate(entry, entry.name + " copy")
                self.refresh(select_id=copied.item_id)
                self.changed.emit()
        except Exception as error:
            self.status.setText(str(error))

    @Slot()
    def _delete(self) -> None:
        """Confirm local deletion and report dependent-object constraints."""
        entry = self.selected_entry()
        if entry is None or entry.read_only:
            return
        if QMessageBox.question(self, "Delete object", f'Delete "{entry.name}"?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.library.delete(entry.kind, entry.item_id)
            self.refresh()
            self.changed.emit()
            self._show_toast(f'Deleted "{entry.name}".')
        except Exception as error:
            self.status.setText(str(error))
            self._show_toast(f'Could not delete "{entry.name}". {error}')

    @Slot()
    def _load(self) -> None:
        """Dispatch a selected compiled prescription or output-stage configuration."""
        try:
            entry = self.selected_entry()
            if entry is None or not self.board_loadable or not self._connected or self._loading_id:
                return
            prescription = self.library.board_prescription(entry)
            if not self.controller.load_prescription(prescription):
                self.status.setText("The board is busy. Try again after the current operation.")
        except Exception as error:
            self.status.setText(str(error))

    @Slot(object)
    def _session(self, _session) -> None:
        """Enable board loading after session validation."""
        self._connected = True
        self.status.setText("Board connected. Ready to load selected values.")
        self._selected()

    @Slot(str)
    def _disconnected(self, _address) -> None:
        """Stop session-scoped loading without disturbing local libraries."""
        self._connected = False
        if self._loading_id:
            self.status.setText("Disconnected. Earlier parameters may be committed; reconnect before retrying.")
        else:
            self.status.setText("Connect a compatible board to load the selected values.")
        self._loading_id = None
        self._owns_transfer = False
        self._selected()

    @Slot(object)
    def _load_started(self, prescription) -> None:
        """Track the controller's single transfer slot across all screens."""
        self._loading_id = prescription.profile_id
        ids = {int(parameter.parameter_id) for parameter in prescription.parameters}
        self._owns_transfer = (self.kind == "outputs" and ids == {14, 15}) or (self.kind == "compiled" and ids == set(range(3, 14)))
        self._loading_name = prescription.display_name
        self.status.setText(f"Loading {prescription.display_name}…" if self._owns_transfer else "Another board transfer is in progress.")
        self.progress.setVisible(self._owns_transfer)
        self.progress.setRange(0, prescription.payload_byte_count)
        self.progress.setValue(0)
        self._selected()

    @Slot(object)
    def _load_progress(self, progress) -> None:
        """Show only firmware-confirmed parameter and byte progress."""
        if self._owns_transfer and progress.profile_id == self._loading_id:
            self.progress.setValue(progress.completed_bytes)
            self.status.setText(f"Stored {progress.completed_parameters}/{progress.total_parameters} parameters · "
                                f"{progress.completed_bytes}/{progress.total_bytes} bytes")

    @Slot(object)
    def _loaded(self, result) -> None:
        """Report board persistence without claiming prescription atomicity."""
        self._loading_id = None
        if self._owns_transfer:
            self.progress.setValue(self.progress.maximum())
            self.status.setText(f"Stored {self._loading_name}: {result.parameter_count} parameters · revision {result.parameter_revision}.")
        else:
            self.status.setText("Board connected. Ready to load selected values.")
        self._owns_transfer = False
        self._selected()

    @Slot(str, str)
    def _load_failed(self, _profile_id, message) -> None:
        """Surface partial multi-parameter progress from the shared loader."""
        self._loading_id = None
        self.status.setText(message if self._owns_transfer else "Board transfer ended. Ready to retry.")
        self._owns_transfer = False
        self._selected()
