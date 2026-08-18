"""Exercise the discovery screen with synchronous controller signals."""

import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget

from tiresias_workstation.devices import DiscoveredDevice
from tiresias_workstation.main_window import MainWindow


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

    def __init__(self):
        super().__init__()
        self.device = DiscoveredDevice(
            address="AA:BB:CC:DD:EE:FF",
            name="Tiresias DK",
            rssi=-52,
            service_uuids=("0000180f-0000-1000-8000-00805f9b34fb",),
        )
        self.connect_attempts = []
        self.shutdown_called = False

    def scan(self):
        self.scan_started.emit()
        self.device_discovered.emit(self.device)
        self.scan_finished.emit([self.device])
        return True

    def connect(self, address):
        self.connect_attempts.append(address)
        self.connection_started.emit(address)
        self.connection_succeeded.emit(address)
        return True

    def disconnect(self):
        self.disconnection_started.emit(self.device.address)
        self.disconnected.emit(self.device.address)
        return True

    def shutdown(self):
        self.shutdown_called = True


class DeviceDiscoveryScreenTest(unittest.TestCase):
    """Verify table population, actions, and window resource ownership."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = FakeController()
        self.window = MainWindow(self.controller)
        self.screen = self.window.device_discovery_screen

    def tearDown(self):
        self.window.close()

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

    def test_closing_window_shuts_down_controller(self):
        """Ensure closing the owner window shuts down its controller."""
        self.window.close()
        self.assertTrue(self.controller.shutdown_called)


if __name__ == "__main__":
    unittest.main()
