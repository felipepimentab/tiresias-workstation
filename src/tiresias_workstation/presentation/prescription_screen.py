"""Present the prescription catalog and board-loading progress."""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tiresias_workstation.application.ble_controller import BleController
from tiresias_workstation.application.prescription_loader import (
    PrescriptionLoadProgress,
    PrescriptionLoadResult,
)
from tiresias_workstation.domain.prescriptions import (
    Prescription,
    PrescriptionCatalog,
)
from tiresias_workstation.domain.tiresias import DeviceSession, ProtocolCapability


class PrescriptionScreen(QWidget):
    """Select catalog entries and invoke the reusable loading pipeline.

    The widget owns no transfer sequencing. It passes a validated
    :class:`Prescription` to :class:`BleController` and renders application
    progress signals on Qt's UI thread.

    Attributes:
        _controller: Shared application coordinator owned by the main window.
        _prescriptions: Available prescriptions indexed by stable profile ID.
        _session: Current compatible board session, or ``None``.
        _loading_profile_id: Profile currently being transferred, or ``None``.
    """

    def __init__(
        self,
        controller: BleController,
        catalog: PrescriptionCatalog,
    ) -> None:
        """Build the catalog screen and subscribe to controller results.

        Args:
            controller: Shared BLE/application controller.
            catalog: Prescription provider independent of asset storage.
        """
        super().__init__()
        self._controller = controller
        self._catalog = catalog
        prescriptions = catalog.list_prescriptions()
        self._prescriptions = {
            prescription.profile_id: prescription
            for prescription in prescriptions
        }
        self._session: DeviceSession | None = None
        self._loading_profile_id: str | None = None
        self._build_ui(prescriptions)
        self._connect_signals()
        self._selection_changed()

    def _build_ui(self, prescriptions: tuple[Prescription, ...]) -> None:
        """Construct the catalog, selected-profile details, and progress view."""
        self.setObjectName("prescriptionScreen")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 30)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        heading_copy = QVBoxLayout()
        heading_copy.setSpacing(3)
        title = QLabel("Prescriptions")
        title.setObjectName("prescriptionTitle")
        heading_copy.addWidget(title)
        subtitle = QLabel(
            "Select a bundled or locally generated parameter profile and "
            "persist it to the connected Tiresias Board."
        )
        subtitle.setObjectName("prescriptionSubtitle")
        subtitle.setWordWrap(True)
        heading_copy.addWidget(subtitle)
        heading.addLayout(heading_copy, 1)
        self._connection_badge = QLabel("Board disconnected")
        self._connection_badge.setObjectName("prescriptionConnectionBadge")
        self._connection_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.addWidget(
            self._connection_badge, 0, Qt.AlignmentFlag.AlignTop
        )
        layout.addLayout(heading)

        self._table = QTableWidget(0, 4)
        self._table.setObjectName("prescriptionTable")
        self._table.setHorizontalHeaderLabels(
            ["Profile", "Description", "Parameters", "Payload"]
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(42)
        header = self._table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 190)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._populate_catalog(prescriptions)
        layout.addWidget(self._table, 1)

        selected_card = QFrame()
        selected_card.setObjectName("selectedPrescriptionCard")
        card_layout = QVBoxLayout(selected_card)
        card_layout.setContentsMargins(16, 13, 16, 13)
        card_layout.setSpacing(7)
        action_row = QHBoxLayout()
        self._selected_title = QLabel("Select a prescription")
        self._selected_title.setObjectName("selectedPrescriptionTitle")
        self._selected_title.setWordWrap(True)
        action_row.addWidget(self._selected_title, 1)
        self._load_button = QPushButton("Load into board")
        self._load_button.setObjectName("loadPrescriptionButton")
        action_row.addWidget(self._load_button)
        card_layout.addLayout(action_row)
        self._selected_details = QLabel()
        self._selected_details.setObjectName("selectedPrescriptionDetails")
        self._selected_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._selected_details.setWordWrap(True)
        card_layout.addWidget(self._selected_details)

        progress_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setObjectName("prescriptionProgress")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        progress_row.addWidget(self._progress, 1)
        self._progress_count = QLabel("0 / 0 parameters")
        self._progress_count.setObjectName("prescriptionProgressCount")
        progress_row.addWidget(self._progress_count)
        card_layout.addLayout(progress_row)
        self._message = QLabel(
            "Connect a compatible board before loading a prescription."
        )
        self._message.setObjectName("prescriptionMessage")
        self._message.setWordWrap(True)
        card_layout.addWidget(self._message)
        layout.addWidget(selected_card)

        if prescriptions:
            self._table.selectRow(0)

    def _connect_signals(self) -> None:
        """Connect user intent and application-pipeline results."""
        self._table.itemSelectionChanged.connect(self._selection_changed)
        self._load_button.clicked.connect(self._load_selected)
        self._controller.session_loaded.connect(self._session_loaded)
        self._controller.disconnected.connect(self._disconnected)
        self._controller.prescription_load_started.connect(self._load_started)
        self._controller.prescription_load_progress.connect(self._load_progress)
        self._controller.prescription_loaded.connect(self._load_completed)
        self._controller.prescription_load_failed.connect(self._load_failed)

    def _populate_catalog(
        self, prescriptions: tuple[Prescription, ...]
    ) -> None:
        """Render catalog metadata without interpreting opaque DSP values."""
        self._table.setRowCount(len(prescriptions))
        for row, prescription in enumerate(prescriptions):
            profile = QTableWidgetItem(prescription.display_name)
            profile.setToolTip(prescription.display_name)
            profile.setData(Qt.ItemDataRole.UserRole, prescription.profile_id)
            description = QTableWidgetItem(prescription.description)
            description.setToolTip(prescription.description)
            values = (
                profile,
                description,
                QTableWidgetItem(str(len(prescription.parameters))),
                QTableWidgetItem(f"{prescription.payload_byte_count} bytes"),
            )
            for column, item in enumerate(values):
                self._table.setItem(row, column, item)

    @Slot()
    @Slot(str)
    def refresh_catalog(self, _artifact_id: str = "") -> None:
        """Reload bundled and mutable catalog entries while preserving selection."""
        selected = self._selected_prescription()
        selected_id = selected.profile_id if selected is not None else None
        prescriptions = self._catalog.list_prescriptions()
        self._prescriptions = {
            prescription.profile_id: prescription for prescription in prescriptions
        }
        self._populate_catalog(prescriptions)
        selected_row = 0 if prescriptions else -1
        if selected_id is not None:
            for row, prescription in enumerate(prescriptions):
                if prescription.profile_id == selected_id:
                    selected_row = row
                    break
        if selected_row >= 0:
            self._table.selectRow(selected_row)
        self._selection_changed()

    @Slot(object)
    def _session_loaded(self, payload: object) -> None:
        """Enable loading after the controller validates a board session."""
        if not isinstance(payload, DeviceSession):
            return
        self._session = payload
        self._connection_badge.setText("Board ready")
        deferred = bool(
            payload.protocol.capabilities
            & ProtocolCapability.DSP_APPLY_DEFERRED
        )
        self._show_message(
            "Prescription bytes will be persisted; live DSP application is "
            "deferred by this firmware."
            if deferred
            else "Ready to persist and apply the selected prescription."
        )
        self._update_actions()

    @Slot(str)
    def _disconnected(self, _address: str) -> None:
        """Reset transfer state after link loss or explicit disconnection."""
        self._session = None
        self._loading_profile_id = None
        self._connection_badge.setText("Board disconnected")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_count.setText("0 / 0 parameters")
        self._show_message(
            "Connect a compatible board before loading a prescription."
        )
        self._update_actions()

    @Slot()
    def _selection_changed(self) -> None:
        """Render selected prescription metadata and action availability."""
        prescription = self._selected_prescription()
        if prescription is None:
            self._selected_title.setText("Select a prescription")
            self._selected_details.clear()
        else:
            self._selected_title.setText(
                f"{prescription.display_name} · "
                f"{len(prescription.parameters)} parameters"
            )
            self._selected_details.setText(
                f"Format: {prescription.format_name} v"
                f"{prescription.format_version} · SHA-256 "
                f"{prescription.sha256}"
            )
            if self._loading_profile_id is None:
                self._progress.setRange(0, prescription.payload_byte_count)
                self._progress.setValue(0)
                self._progress_count.setText(
                    f"0 / {len(prescription.parameters)} parameters"
                )
        self._update_actions()

    @Slot()
    def _load_selected(self) -> None:
        """Submit the selected validated prescription to the shared pipeline."""
        prescription = self._selected_prescription()
        if prescription is None:
            return
        if not self._controller.load_prescription(prescription):
            self._show_message(
                "Another board operation is active; try again when it finishes.",
                error=True,
            )

    @Slot(object)
    def _load_started(self, payload: object) -> None:
        """Initialize determinate progress for an accepted prescription."""
        if not isinstance(payload, Prescription):
            return
        self._loading_profile_id = payload.profile_id
        self._progress.setRange(0, payload.payload_byte_count)
        self._progress.setValue(0)
        self._progress_count.setText(
            f"0 / {len(payload.parameters)} parameters"
        )
        self._show_message(f"Loading {payload.profile_id} into the board…")
        self._update_actions()

    @Slot(object)
    def _load_progress(self, payload: object) -> None:
        """Render one firmware-confirmed parameter persistence step."""
        if not isinstance(payload, PrescriptionLoadProgress):
            return
        if payload.profile_id != self._loading_profile_id:
            return
        self._progress.setValue(payload.completed_bytes)
        self._progress_count.setText(
            f"{payload.completed_parameters} / "
            f"{payload.total_parameters} parameters"
        )
        self._show_message(
            f"Persisted parameter {payload.parameter_id} · board revision "
            f"{payload.parameter_revision}."
        )

    @Slot(object)
    def _load_completed(self, payload: object) -> None:
        """Report only a fully confirmed prescription as loaded."""
        if not isinstance(payload, PrescriptionLoadResult):
            return
        self._loading_profile_id = None
        self._progress.setValue(payload.payload_byte_count)
        self._progress_count.setText(
            f"{payload.parameter_count} / {payload.parameter_count} parameters"
        )
        deferred = bool(
            self._session
            and self._session.protocol.capabilities
            & ProtocolCapability.DSP_APPLY_DEFERRED
        )
        suffix = " DSP application is deferred." if deferred else ""
        self._show_message(
            f"{payload.profile_id} loaded · {payload.payload_byte_count} bytes "
            f"persisted · board revision {payload.parameter_revision}.{suffix}"
        )
        self._update_actions()

    @Slot(str, str)
    def _load_failed(self, profile_id: str, message: str) -> None:
        """Report a failed or partially completed transfer without ambiguity."""
        self._loading_profile_id = None
        self._show_message(f"Could not load {profile_id}: {message}", error=True)
        self._update_actions()

    def _selected_prescription(self) -> Prescription | None:
        """Return the selected catalog entry by stable profile ID."""
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        return self._prescriptions.get(item.data(Qt.ItemDataRole.UserRole))

    def _update_actions(self) -> None:
        """Enable loading only for a selected profile and ready idle board."""
        self._load_button.setEnabled(
            self._session is not None
            and self._loading_profile_id is None
            and self._selected_prescription() is not None
        )
        self._table.setEnabled(self._loading_profile_id is None)

    def _show_message(self, text: str, *, error: bool = False) -> None:
        """Render transfer status with contextual error styling."""
        self._message.setText(text)
        self._message.setProperty("error", error)
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
