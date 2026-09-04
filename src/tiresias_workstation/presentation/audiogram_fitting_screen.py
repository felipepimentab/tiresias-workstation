"""Present audiogram entry and the complete custom-prescription workflow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tiresias_workstation.application.prescription_workbench import (
    PrescriptionWorkbench,
)
from tiresias_workstation.domain.fittings import Audiogram, GeneratedPrescription


DEFAULT_AUDIOGRAM_FREQUENCIES_HZ = (
    250.0,
    375.0,
    500.0,
    750.0,
    1000.0,
    1500.0,
    2000.0,
    3000.0,
    4000.0,
    6000.0,
)


class _GenerationSignals(QObject):
    """Carry background prescription results back to the Qt UI thread.

    Signals:
        completed(object): Emits the generated prescription artifact.
        failed(str): Emits a terminal fitting or mapping error message.
    """

    completed = Signal(object)
    failed = Signal(str)


class _GenerationTask(QRunnable):
    """Run pyClarity and DSP mapping without blocking Qt event processing."""

    def __init__(
        self,
        workbench: PrescriptionWorkbench,
        audiogram: Audiogram,
        rule_id: str,
        name: str,
        ear: str,
    ) -> None:
        """Capture normalized generation inputs before leaving the UI thread."""
        super().__init__()
        self._workbench = workbench
        self._audiogram = audiogram
        self._rule_id = rule_id
        self._name = name
        self._ear = ear
        self.signals = _GenerationSignals()

    @Slot()
    def run(self) -> None:
        """Generate an artifact and publish one terminal result."""
        try:
            artifact = self._workbench.generate(
                self._audiogram,
                rule_id=self._rule_id,
                name=self._name,
                ear=self._ear,
            )
        except Exception as error:  # Report adapter failures at the UI boundary.
            self.signals.failed.emit(str(error))
            return
        self.signals.completed.emit(artifact)


class AudiogramFittingScreen(QWidget):
    """Generate, inspect, save, export, list, and delete custom prescriptions.

    Signals:
        prescription_saved(str): Emitted with the stable artifact ID after a
            generated prescription is stored locally.
        prescription_deleted(str): Emitted with the stable artifact ID after a
            local prescription is deleted.
    """

    prescription_saved = Signal(str)
    prescription_deleted = Signal(str)

    def __init__(self, workbench: PrescriptionWorkbench) -> None:
        """Build the fitting workflow around an application workbench."""
        super().__init__()
        self._workbench = workbench
        self._current_artifact: GeneratedPrescription | None = None
        self._generation_task: _GenerationTask | None = None
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(1)
        self._build_ui()
        self._connect_signals()
        self.refresh_saved()

    def _build_ui(self) -> None:
        """Construct audiogram, target preview, and local catalog controls."""
        self.setObjectName("audiogramFittingScreen")
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 30)
        root.setSpacing(14)

        title = QLabel("Audiogram fitting")
        title.setObjectName("fittingTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Create a prescription from an audiogram. Preview, save, or export "
            "every stage — no board connection required."
        )
        subtitle.setObjectName("fittingSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self._name = QLineEdit()
        self._name.setObjectName("customPrescriptionName")
        self._name.setMaxLength(80)
        self._name.setPlaceholderText("Custom prescription name")
        self._name.setMinimumWidth(140)
        self._rule = QComboBox()
        self._rule.setObjectName("prescriptionRuleSelector")
        for rule in self._workbench.list_rules():
            self._rule.addItem(rule.display_name, rule.rule_id)
        self._rule.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._rule.setMinimumContentsLength(18)
        self._ear = QComboBox()
        self._ear.setObjectName("dspEarSelector")
        self._ear.addItem("Left", "left")
        self._ear.addItem("Right", "right")
        for label_text, field, stretch in (
            ("Prescription name", self._name, 2),
            ("Prescription rule", self._rule, 2),
            ("DSP ear", self._ear, 1),
        ):
            field_layout = QVBoxLayout()
            field_layout.setSpacing(5)
            label = QLabel(label_text)
            label.setProperty("role", "fieldLabel")
            label.setBuddy(field)
            field.setAccessibleName(label_text)
            field_layout.addWidget(label)
            field_layout.addWidget(field)
            controls.addLayout(field_layout, stretch)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(self._build_audiogram_card())
        splitter.addWidget(self._build_result_card())
        splitter.setSizes([420, 560])
        root.addWidget(splitter, 4)

        saved_header = QHBoxLayout()
        saved_title = QLabel("Saved custom prescriptions")
        saved_title.setObjectName("savedPrescriptionTitle")
        saved_header.addWidget(saved_title, 1)
        self._export_saved = QPushButton("Export selected…")
        self._export_saved.setObjectName("exportSavedPrescriptionButton")
        self._delete_saved = QPushButton("Delete selected")
        self._delete_saved.setObjectName("deleteSavedPrescriptionButton")
        saved_header.addWidget(self._export_saved)
        saved_header.addWidget(self._delete_saved)
        root.addLayout(saved_header)

        self._saved_table = QTableWidget(0, 5)
        self._saved_table.setObjectName("savedPrescriptionTable")
        self._saved_table.setHorizontalHeaderLabels(
            ["Name", "Rule", "DSP ear", "Created", "Parameters"]
        )
        self._saved_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._saved_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._saved_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._saved_table.verticalHeader().hide()
        self._saved_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._saved_table.verticalHeader().setDefaultSectionSize(34)
        self._saved_table.setShowGrid(False)
        self._saved_table.setMinimumHeight(90)
        self._saved_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 5):
            self._saved_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        root.addWidget(self._saved_table, 1)

        self._message = QLabel(
            "Enter thresholds for both ears, then generate a target."
        )
        self._message.setObjectName("fittingMessage")
        self._message.setWordWrap(True)
        root.addWidget(self._message)

    def _build_audiogram_card(self) -> QFrame:
        """Build the editable two-ear audiogram table."""
        card = QFrame()
        card.setObjectName("fittingCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel("Audiogram · dB HL")
        heading.setObjectName("fittingCardTitle")
        layout.addWidget(heading)
        self._audiogram_table = QTableWidget(
            len(DEFAULT_AUDIOGRAM_FREQUENCIES_HZ), 3
        )
        self._audiogram_table.setObjectName("audiogramTable")
        self._audiogram_table.setHorizontalHeaderLabels(
            ["Hz", "Left", "Right"]
        )
        self._audiogram_table.verticalHeader().hide()
        self._audiogram_table.verticalHeader().setDefaultSectionSize(28)
        self._audiogram_table.setShowGrid(False)
        self._audiogram_table.setAlternatingRowColors(True)
        self._audiogram_table.setAccessibleName("Audiogram thresholds in dB HL")
        self._audiogram_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        for row, frequency in enumerate(DEFAULT_AUDIOGRAM_FREQUENCIES_HZ):
            frequency_item = QTableWidgetItem(f"{frequency:g}")
            frequency_item.setFlags(
                frequency_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            self._audiogram_table.setItem(row, 0, frequency_item)
            self._audiogram_table.setItem(row, 1, QTableWidgetItem("0"))
            self._audiogram_table.setItem(row, 2, QTableWidgetItem("0"))
            for column in range(3):
                self._audiogram_table.item(row, column).setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
        layout.addWidget(self._audiogram_table, 1)
        self._generate = QPushButton("Generate prescription")
        self._generate.setToolTip("Generate the target curves and calibrated DSP values")
        self._generate.setObjectName("generatePrescriptionButton")
        layout.addWidget(self._generate)
        return card

    def _build_result_card(self) -> QFrame:
        """Build the target preview and save/export actions."""
        card = QFrame()
        card.setObjectName("fittingCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        self._result_title = QLabel("No generated target")
        self._result_title.setObjectName("fittingCardTitle")
        self._result_title.setWordWrap(True)
        layout.addWidget(self._result_title)
        self._result_details = QLabel(
            "The preview shows target gain at representative acoustic input levels."
        )
        self._result_details.setObjectName("resultDetails")
        self._result_details.setWordWrap(True)
        self._result_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._result_details)
        self._target_table = QTableWidget(0, 7)
        self._target_table.setObjectName("prescriptionTargetTable")
        self._target_table.setHorizontalHeaderLabels(
            ["Hz", "L 45", "L 65", "L 85", "R 45", "R 65", "R 85"]
        )
        self._target_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._target_table.verticalHeader().hide()
        self._target_table.verticalHeader().setDefaultSectionSize(28)
        self._target_table.setShowGrid(False)
        self._target_table.setAlternatingRowColors(True)
        self._target_table.setAccessibleName("Target gains in dB at 45, 65, and 85 dB SPL")
        self._target_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self._target_table, 1)
        actions = QHBoxLayout()
        self._save = QPushButton("Save locally")
        self._save.setObjectName("saveGeneratedPrescriptionButton")
        self._save.setEnabled(False)
        self._export_current = QPushButton("Export JSON…")
        self._export_current.setObjectName("exportGeneratedPrescriptionButton")
        self._export_current.setEnabled(False)
        actions.addWidget(self._save)
        actions.addWidget(self._export_current)
        layout.addLayout(actions)
        return card

    def _connect_signals(self) -> None:
        """Connect fitting and local-catalog user actions."""
        self._generate.clicked.connect(self._generate_artifact)
        self._save.clicked.connect(self._save_current)
        self._export_current.clicked.connect(self._export_current_artifact)
        self._saved_table.itemSelectionChanged.connect(self._saved_selection_changed)
        self._export_saved.clicked.connect(self._export_saved_artifact)
        self._delete_saved.clicked.connect(self._delete_saved_artifact)

    @Slot()
    def _generate_artifact(self) -> None:
        """Validate UI inputs and schedule the rule and mapper off-thread."""
        try:
            audiogram = self._read_audiogram()
            rule_id = str(self._rule.currentData())
            ear = str(self._ear.currentData())
            if ear not in ("left", "right"):
                raise ValueError("Select a DSP target ear.")
            name = self._name.text().strip()
            if not name:
                raise ValueError("A custom prescription name is required.")
        except (AttributeError, TypeError, ValueError) as error:
            self._show_message(str(error), error=True)
            return
        self._generate.setEnabled(False)
        self._audiogram_table.setEnabled(False)
        self._name.setEnabled(False)
        self._rule.setEnabled(False)
        self._ear.setEnabled(False)
        self._show_message("Generating the prescription target and DSP values…")
        task = _GenerationTask(
            self._workbench,
            audiogram,
            rule_id,
            name,
            ear,
        )
        task.signals.completed.connect(self._generation_completed)
        task.signals.failed.connect(self._generation_failed)
        self._generation_task = task
        self._thread_pool.start(task)

    @Slot(object)
    def _generation_completed(self, payload: object) -> None:
        """Render a generated artifact delivered on the Qt UI thread."""
        self._generation_finished()
        if not isinstance(payload, GeneratedPrescription):
            self._show_message(
                "The prescription rule returned an invalid result.", error=True
            )
            return
        artifact = payload
        self._show_artifact(artifact)
        self._save.setEnabled(True)
        self._show_message(
            "Generated all stages in memory. Save locally or export the "
            "complete JSON artifact."
        )

    @Slot(str)
    def _generation_failed(self, message: str) -> None:
        """Report a terminal background rule or mapping failure."""
        self._generation_finished()
        self._show_message(message, error=True)

    def _generation_finished(self) -> None:
        """Release one task and restore fitting input actions."""
        self._generation_task = None
        self._generate.setEnabled(True)
        self._audiogram_table.setEnabled(True)
        self._name.setEnabled(True)
        self._rule.setEnabled(True)
        self._ear.setEnabled(True)

    def _read_audiogram(self) -> Audiogram:
        """Normalize editable table cells into the domain audiogram."""
        frequencies: list[float] = []
        left: list[float] = []
        right: list[float] = []
        for row in range(self._audiogram_table.rowCount()):
            try:
                frequencies.append(float(self._audiogram_table.item(row, 0).text()))
                left.append(float(self._audiogram_table.item(row, 1).text()))
                right.append(float(self._audiogram_table.item(row, 2).text()))
            except (AttributeError, ValueError) as error:
                raise ValueError(
                    f"Enter numeric left and right thresholds in row {row + 1}."
                ) from error
        return Audiogram(tuple(frequencies), tuple(left), tuple(right))

    def _show_artifact(self, artifact: GeneratedPrescription) -> None:
        """Render target checkpoints and final parameter metadata."""
        self._current_artifact = artifact
        target = artifact.target
        self._name.setText(artifact.name)
        self._ear.setCurrentIndex(self._ear.findData(artifact.mapping.ear))
        self._rule.setCurrentIndex(self._rule.findData(target.rule.rule_id))
        audiogram = target.audiogram
        self._audiogram_table.setRowCount(len(audiogram.frequencies_hz))
        for row, values in enumerate(zip(
            audiogram.frequencies_hz,
            audiogram.left_levels_db_hl,
            audiogram.right_levels_db_hl,
        )):
            for column, value in enumerate(values):
                item = QTableWidgetItem(f"{value:g}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._audiogram_table.setItem(row, column, item)
        self._result_title.setText(artifact.name)
        self._result_details.setText(
            f"{len(target.band_centres_hz)} bands · "
            f"{len(target.input_levels_db_spl)} levels · "
            f"{artifact.mapping.ear.title()} ear to DSP\n"
            f"{len(artifact.prescription.parameters)} parameters / "
            f"{artifact.prescription.payload_byte_count} bytes · SHA-256 "
            f"{artifact.prescription.sha256[:12]}…"
        )
        self._result_details.setToolTip(
            f"{target.rule.display_name}\nSHA-256: {artifact.prescription.sha256}"
        )
        active_bands = min(8, len(target.band_centres_hz))
        self._target_table.setRowCount(active_bands)
        for row in range(active_bands):
            values = [f"{target.band_centres_hz[row]:g}"]
            values.extend(
                f"{target.gain_at('left', row, level):.2f}"
                for level in (45.0, 65.0, 85.0)
            )
            values.extend(
                f"{target.gain_at('right', row, level):.2f}"
                for level in (45.0, 65.0, 85.0)
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._target_table.setItem(row, column, item)
        self._export_current.setEnabled(True)

    @Slot()
    def _save_current(self) -> None:
        """Persist the current in-memory artifact and refresh the local list."""
        if self._current_artifact is None:
            return
        try:
            self._workbench.save(self._current_artifact)
        except (OSError, TypeError, ValueError) as error:
            self._show_message(f"Could not save prescription: {error}", error=True)
            return
        artifact_id = self._current_artifact.artifact_id
        self.refresh_saved(select_artifact_id=artifact_id)
        self._save.setEnabled(False)
        self.prescription_saved.emit(artifact_id)
        self._show_message(
            "Saved locally. The prescription is now available in the "
            "board-loading catalog."
        )

    def refresh_saved(self, *, select_artifact_id: str | None = None) -> None:
        """Reload the local catalog and optionally restore one selection."""
        try:
            artifacts = self._workbench.list_saved()
        except (OSError, TypeError, ValueError) as error:
            self._show_message(
                f"Could not read saved prescriptions: {error}", error=True
            )
            return
        self._saved_table.setRowCount(len(artifacts))
        selected_row = -1
        for row, artifact in enumerate(artifacts):
            name = QTableWidgetItem(artifact.name)
            name.setData(Qt.ItemDataRole.UserRole, artifact.artifact_id)
            name.setToolTip(artifact.name)
            try:
                created_at = datetime.fromisoformat(artifact.created_at).astimezone()
                created_text = created_at.strftime("%d %b %Y, %H:%M")
            except ValueError:
                created_text = artifact.created_at
            created = QTableWidgetItem(created_text)
            created.setToolTip(artifact.created_at)
            values = (
                name,
                QTableWidgetItem(artifact.target.rule.display_name),
                QTableWidgetItem(artifact.mapping.ear.title()),
                created,
                QTableWidgetItem(str(len(artifact.prescription.parameters))),
            )
            for column, item in enumerate(values):
                self._saved_table.setItem(row, column, item)
            if artifact.artifact_id == select_artifact_id:
                selected_row = row
        if selected_row >= 0:
            self._saved_table.selectRow(selected_row)
        self._update_saved_actions()

    @Slot()
    def _saved_selection_changed(self) -> None:
        """Inspect the selected saved artifact using the same preview."""
        artifact_id = self._selected_saved_id()
        if artifact_id is not None:
            try:
                self._show_artifact(self._workbench.get_saved(artifact_id))
                self._save.setEnabled(False)
                self._show_message(
                    "Inspecting a saved prescription. Edit the inputs and generate "
                    "again to create a new prescription; the saved copy is unchanged."
                )
            except (KeyError, OSError, TypeError, ValueError) as error:
                self._show_message(
                    f"Could not inspect saved prescription: {error}", error=True
                )
        self._update_saved_actions()

    @Slot()
    def _delete_saved_artifact(self) -> None:
        """Confirm and delete the selected locally generated artifact."""
        artifact_id = self._selected_saved_id()
        if artifact_id is None:
            return
        try:
            artifact = self._workbench.get_saved(artifact_id)
        except (KeyError, OSError, TypeError, ValueError) as error:
            self._show_message(f"Could not read prescription: {error}", error=True)
            return
        answer = QMessageBox.question(
            self,
            "Delete custom prescription",
            f"Delete \"{artifact.name}\" from this workstation?\n\n"
            "The local file will be removed. Exported copies are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._workbench.delete(artifact_id)
        except (KeyError, OSError, ValueError) as error:
            self._show_message(f"Could not delete prescription: {error}", error=True)
            return
        if self._current_artifact and self._current_artifact.artifact_id == artifact_id:
            self._current_artifact = None
            self._result_title.setText("No generated target")
            self._result_details.clear()
            self._target_table.setRowCount(0)
            self._export_current.setEnabled(False)
            self._save.setEnabled(False)
        self.refresh_saved()
        self.prescription_deleted.emit(artifact_id)
        self._show_message("Deleted the local custom prescription.")

    @Slot()
    def _export_current_artifact(self) -> None:
        """Export the current generated or inspected artifact."""
        if self._current_artifact is not None:
            self._choose_export_path(self._current_artifact)

    @Slot()
    def _export_saved_artifact(self) -> None:
        """Export the selected saved artifact without modifying the catalog."""
        artifact_id = self._selected_saved_id()
        if artifact_id is not None:
            try:
                artifact = self._workbench.get_saved(artifact_id)
            except (KeyError, OSError, TypeError, ValueError) as error:
                self._show_message(f"Could not read prescription: {error}", error=True)
                return
            self._choose_export_path(artifact)

    def _choose_export_path(self, artifact: GeneratedPrescription) -> None:
        """Prompt for a portable JSON destination and write the artifact."""
        path_text, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export generated prescription",
            f"{artifact.artifact_id}.json",
            "JSON files (*.json)",
        )
        if not path_text:
            return
        path = Path(path_text)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            self._workbench.export(artifact, path)
        except OSError as error:
            self._show_message(f"Could not export prescription: {error}", error=True)
            return
        self._show_message(f"Exported all stages to {path}.")

    def _selected_saved_id(self) -> str | None:
        """Return the selected local artifact identifier."""
        row = self._saved_table.currentRow()
        if row < 0:
            return None
        item = self._saved_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _update_saved_actions(self) -> None:
        """Enable saved-artifact actions only when one row is selected."""
        selected = self._selected_saved_id() is not None
        self._export_saved.setEnabled(selected)
        self._delete_saved.setEnabled(selected)

    def _show_message(self, text: str, *, error: bool = False) -> None:
        """Render a workflow message with contextual error styling."""
        self._message.setText(text)
        self._message.setProperty("error", error)
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
