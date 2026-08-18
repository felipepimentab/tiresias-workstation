"""Exercise the Qt-to-asyncio Bluetooth controller with a fake transport."""

import asyncio
import time
import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from tiresias_workstation.ble_controller import BleController
from tiresias_workstation.devices import DiscoveredDevice


class FakeTransport:
    """Provide deterministic asynchronous operations without BLE hardware."""

    def __init__(self) -> None:
        """Initialize fake connection state and callback storage."""
        self.connected_address: str | None = None
        self.disconnected_callback = None

    async def scan(self, on_device, *, timeout):
        del timeout
        devices = [
            DiscoveredDevice(
                address="AA:BB:CC:DD:EE:FF",
                name="Tiresias DK",
                rssi=-48,
                service_uuids=("0000180f-0000-1000-8000-00805f9b34fb",),
            )
        ]
        on_device(devices[0])
        await asyncio.sleep(0)
        return devices

    async def connect(self, address, on_disconnected, *, timeout):
        del timeout
        await asyncio.sleep(0)
        self.connected_address = address
        self.disconnected_callback = on_disconnected

    async def disconnect(self):
        await asyncio.sleep(0)
        address = self.connected_address
        self.connected_address = None
        if address is not None and self.disconnected_callback is not None:
            self.disconnected_callback(address)


class BleControllerTest(unittest.TestCase):
    """Verify operation scheduling, signals, and lifecycle behavior."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.transport = FakeTransport()
        self.controller = BleController(
            transport_factory=lambda: self.transport,
            scan_timeout=0,
            connection_timeout=0.1,
        )

    def tearDown(self):
        self.controller.shutdown()

    def wait_for_signal(self, spy, timeout=1.0):
        """Process Qt events until a signal arrives or the timeout expires."""
        deadline = time.monotonic() + timeout
        while spy.count() == 0 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertGreater(spy.count(), 0)

    def test_scan_connect_and_disconnect(self):
        """Complete the primary device lifecycle through controller signals."""
        discovered_spy = QSignalSpy(self.controller.device_discovered)
        scan_spy = QSignalSpy(self.controller.scan_finished)

        self.assertTrue(self.controller.scan())
        self.wait_for_signal(scan_spy)
        self.assertEqual(discovered_spy.count(), 1)
        devices = scan_spy.at(0)[0]
        self.assertEqual(devices[0].name, "Tiresias DK")

        connected_spy = QSignalSpy(self.controller.connection_succeeded)
        self.assertTrue(self.controller.connect(devices[0].address))
        self.wait_for_signal(connected_spy)
        self.assertEqual(self.transport.connected_address, devices[0].address)

        disconnected_spy = QSignalSpy(self.controller.disconnected)
        self.assertTrue(self.controller.disconnect())
        self.wait_for_signal(disconnected_spy)
        self.assertIsNone(self.transport.connected_address)


if __name__ == "__main__":
    unittest.main()
