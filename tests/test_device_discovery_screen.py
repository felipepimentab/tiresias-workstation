"""Exercise the discovery screen with synchronous controller signals."""

from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
)

from tiresias_workstation.application.prescription_loader import (
    PrescriptionLoadProgress,
    PrescriptionLoadResult,
)
from tiresias_workstation.application.default_prescriptions import (
    create_default_prescription_services,
)
from tiresias_workstation.domain.devices import DiscoveredDevice
from tiresias_workstation.domain.dsp_contract import DSP_PARAMETERS_BY_ID
from tiresias_workstation.domain.fittings import Audiogram
from test_ble_controller import device_session
from tiresias_workstation.domain.tiresias import ParameterValue
from tiresias_workstation.presentation.main_window import MainWindow
from tiresias_workstation.presentation.theme import apply_light_theme


class FakeController(QObject):
    """Provide the controller signal contract without a worker thread."""

    device_discovered = Signal(object)
    scan_started = Signal()
    scan_finished = Signal(object)
    scan_failed = Signal(str)
    connection_started = Signal(str)
    connection_succeeded = Signal(str)
    connection_failed = Signal(str, str)
    disconnection_started = Signal(str)
    disconnected = Signal(str)
    session_loaded = Signal(object)
    parameter_read_started = Signal(int)
    parameter_read = Signal(object)
    parameter_write_started = Signal(int, object)
    parameter_written = Signal(object)
    parameter_operation_failed = Signal(int, str)
    prescription_load_started = Signal(object)
    prescription_load_progress = Signal(object)
    prescription_loaded = Signal(object)
    prescription_load_failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.device = DiscoveredDevice(
            address="AA:BB:CC:DD:EE:FF",
            name="Tiresias DK",
            rssi=-52,
            service_uuids=("7b9a0001-6e4f-4b2d-a9c8-4f2e6f5d1000",),
            is_tiresias=True,
        )
        self.connect_attempts = []
        self.shutdown_called = False
        self.parameter_writes = []
        self.prescription_loads = []
        self.session = device_session()

    def scan(self):
        self.scan_started.emit()
        self.device_discovered.emit(self.device)
        self.scan_finished.emit([self.device])
        return True

    def connect(self, address):
        self.connect_attempts.append(address)
        self.connection_started.emit(address)
        self.connection_succeeded.emit(address)
        self.session_loaded.emit(self.session)
        return True

    def disconnect(self):
        self.disconnection_started.emit(self.device.address)
        self.disconnected.emit(self.device.address)
        return True

    def shutdown(self):
        self.shutdown_called = True

    def read_parameter(self, parameter_id):
        self.parameter_read_started.emit(parameter_id)
        definition = DSP_PARAMETERS_BY_ID[parameter_id]
        data = (b"\x00\x80\x00\x00" * ((definition.byte_count + 3) // 4))[
            : definition.byte_count
        ]
        self.parameter_read.emit(ParameterValue(parameter_id, data, 4))
        return True

    def write_parameter(self, parameter_id, value):
        self.parameter_writes.append((parameter_id, value))
        self.parameter_write_started.emit(parameter_id, value)
        self.parameter_written.emit(ParameterValue(parameter_id, value, 5))
        return True

    def load_prescription(self, prescription):
        """Synchronously model a complete application-pipeline transfer."""
        self.prescription_loads.append(prescription)
        self.prescription_load_started.emit(prescription)
        completed_bytes = 0
        for completed, parameter in enumerate(prescription.parameters, start=1):
            completed_bytes += len(parameter.data)
            self.prescription_load_progress.emit(
                PrescriptionLoadProgress(
                    prescription.profile_id,
                    completed,
                    len(prescription.parameters),
                    completed_bytes,
                    prescription.payload_byte_count,
                    int(parameter.parameter_id),
                    4 + completed,
                )
            )
        self.prescription_loaded.emit(
            PrescriptionLoadResult(
                prescription.profile_id,
                len(prescription.parameters),
                prescription.payload_byte_count,
                4 + len(prescription.parameters),
            )
        )
        return True


class DeviceDiscoveryScreenTest(unittest.TestCase):
    """Verify table population, actions, and window resource ownership."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_light_theme(cls.app)

    def setUp(self):
        self.controller = FakeController()
        self.directory = tempfile.TemporaryDirectory()
        workbench, catalog = create_default_prescription_services(
            Path(self.directory.name)
        )
        self.window = MainWindow(self.controller, catalog, workbench)
        self.screen = self.window.device_discovery_screen

    def tearDown(self):
        self.window.close()
        self.directory.cleanup()

    def test_scan_populates_table_and_connects_selected_device(self):
        """Render a discovered device and connect the selected table row."""
        scan_button = self.screen.findChild(QPushButton, "scanButton")
        table = self.screen.findChild(QTableWidget, "deviceTable")
        connect_button = self.screen.findChild(QPushButton, "connectButton")

        scan_button.click()
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "Tiresias DK")
        self.assertEqual(table.item(0, 2).text(), "-52 dBm  ·  Strong")

        table.selectRow(0)
        connect_button.click()
        self.assertEqual(
            self.controller.connect_attempts, [self.controller.device.address]
        )
        self.assertTrue(connect_button.isHidden())

    def test_connected_session_displays_dis_and_persists_selected_parameter(self):
        """Navigate from a ready session to ID-based flash parameter control."""
        self.controller.connection_succeeded.emit(self.controller.device.address)
        self.controller.session_loaded.emit(self.controller.session)
        control = self.window.device_control_screen
        table = control.findChild(QTableWidget, "parameterTable")
        value_input = control.findChild(QLineEdit, "parameterValueInput")
        write_button = control.findChild(QPushButton, "writeParameterButton")

        self.window.show()
        self.app.processEvents()
        self.assertTrue(control._title.isVisible())
        self.assertEqual(control._board_values["model"].text(), "Tiresias DK")
        self.assertTrue(control._board_values["model"].isVisible())
        self.assertEqual(control._board_values["firmware"].text(), "0.1.0")
        self.assertTrue(control._board_values["firmware"].isVisible())
        self.assertEqual(table.rowCount(), 15)
        self.assertEqual(table.item(10, 1).text(), "Phase Comp Gain 1")
        self.assertEqual(table.item(10, 2).text(), "Gain")
        self.assertEqual(table.item(10, 5).text(), "00 80 00 00")
        self.assertTrue(table.item(2, 5).text().startswith("136 bytes ·"))
        self.assertTrue(table.item(2, 5).toolTip().startswith("00 80 00 00"))
        table.selectRow(10)
        value_input.setText("01 80 00 00")
        write_button.click()

        self.assertEqual(self.controller.parameter_writes, [(11, b"\x01\x80\x00\x00")])
        self.assertIn("Persisted", control._message.text())

    def test_closing_window_shuts_down_controller(self):
        """Ensure closing the owner window shuts down its controller."""
        self.window.close()
        self.assertTrue(self.controller.shutdown_called)

    def test_selects_and_loads_a_standard_prescription(self):
        """Navigate to the catalog and submit the selected profile."""
        self.controller.connection_succeeded.emit(self.controller.device.address)
        self.controller.session_loaded.emit(self.controller.session)
        navigation = self.window.findChild(
            QPushButton, "prescriptionsNavigationButton"
        )

        navigation.click()
        self.app.processEvents()
        screen = self.window.prescription_screen
        table = screen.findChild(QTableWidget, "prescriptionTable")
        load_button = screen.findChild(QPushButton, "loadPrescriptionButton")
        progress = screen.findChild(QProgressBar, "prescriptionProgress")

        self.assertEqual(table.rowCount(), 10)
        self.assertEqual(table.item(0, 0).text(), "N1 standard audiogram")
        self.assertEqual(table.item(9, 0).text(), "S3 standard audiogram")
        table.selectRow(1)
        load_button.click()

        self.assertEqual(
            [entry.profile_id for entry in self.controller.prescription_loads],
            ["N2"],
        )
        self.assertEqual(progress.maximum(), 1100)
        self.assertEqual(progress.value(), 1100)
        self.assertIn("N2 loaded", screen._message.text())

    def test_local_fitting_is_available_offline_and_refreshes_loading_catalog(self):
        """Reuse the normal board-loading flow for a custom saved prescription."""
        navigation = self.window.findChild(QPushButton, "fittingNavigationButton")
        self.assertTrue(navigation.isEnabled())
        navigation.click()
        fitting = self.window.audiogram_fitting_screen
        artifact = self.window._prescription_workbench.generate(
            Audiogram((250.0, 500.0), (10.0, 20.0), (15.0, 25.0)),
            rule_id="camfit-compressive-cec1", name="My custom fitting", ear="left",
        )
        fitting._show_artifact(artifact)
        fitting._save_current()
        table = self.window.prescription_screen.findChild(
            QTableWidget, "prescriptionTable"
        )
        self.assertEqual(table.rowCount(), 11)
        self.assertEqual(table.item(10, 0).text(), "My custom fitting")
        self.controller.session_loaded.emit(self.controller.session)
        table.selectRow(10)
        self.window.prescription_screen.findChild(
            QPushButton, "loadPrescriptionButton"
        ).click()
        self.assertEqual(self.controller.prescription_loads, [artifact.prescription])


if __name__ == "__main__":
    unittest.main()
