"""Exercise the Qt-to-asyncio Bluetooth controller with a fake transport."""

import asyncio
import time
import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from tiresias_workstation.adapters.bundled_prescriptions import N1_PRESCRIPTION
from tiresias_workstation.application.ble_controller import BleController
from tiresias_workstation.application.prescription_loader import (
    PrescriptionLoadResult,
)
from tiresias_workstation.domain.devices import DiscoveredDevice
from tiresias_workstation.domain.dsp_contract import (
    DSP_PARAMETER_CONTRACT_CRC32,
    DSP_PARAMETERS,
)
from tiresias_workstation.domain.tiresias import (
    DeviceInformation,
    DeviceSession,
    DeviceState,
    DeviceStatus,
    ParameterValue,
    ProtocolCapability,
    ProtocolInformation,
    RequestResult,
    StatusFlag,
)


def device_session():
    """Return one ready session used by controller tests."""
    return DeviceSession(
        DeviceInformation("Tiresias", "Tiresias DK", "1", "A", "0.1.0"),
        ProtocolInformation(
            4,
            0,
            ProtocolCapability(15),
            12,
            16,
            DSP_PARAMETER_CONTRACT_CRC32,
            2,
            3,
        ),
        DeviceStatus(
            DeviceState.READY,
            StatusFlag(7),
            RequestResult.OK,
            3,
            0,
            0,
            0,
        ),
        DSP_PARAMETERS,
    )


class FakeTransport:
    """Provide deterministic asynchronous operations without BLE hardware."""

    def __init__(self) -> None:
        """Initialize fake connection state and callback storage."""
        self.connected_address: str | None = None
        self.disconnected_callback = None
        self.disconnect_during_session_read = False
        self.parameter_writes: list[tuple[int, bytes]] = []

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

    async def read_session(self):
        """Return a session or simulate link loss in the completion race."""
        if self.disconnect_during_session_read:
            address = self.connected_address
            self.connected_address = None
            self.disconnected_callback(address)
        await asyncio.sleep(0)
        return device_session()

    async def read_parameter(self, parameter_id):
        await asyncio.sleep(0)
        return ParameterValue(parameter_id, b"\x00\x80\x00\x00", 4)

    async def write_parameter(self, parameter_id, value):
        self.parameter_writes.append((parameter_id, value))
        await asyncio.sleep(0)
        return ParameterValue(parameter_id, value, 5)


class BleControllerTest(unittest.TestCase):
    """Verify operation scheduling, signals, and lifecycle behavior."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.transport = FakeTransport()
        self.controller = BleController(
            client_factory=lambda: self.transport,
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
        session_spy = QSignalSpy(self.controller.session_loaded)
        self.assertTrue(self.controller.connect(devices[0].address))
        self.wait_for_signal(connected_spy)
        self.assertEqual(self.transport.connected_address, devices[0].address)
        self.assertEqual(session_spy.count(), 1)

        written_spy = QSignalSpy(self.controller.parameter_written)
        self.assertTrue(self.controller.write_parameter(1, b"\x01\x00\x00\x00"))
        self.wait_for_signal(written_spy)
        self.assertEqual(written_spy.at(0)[0].parameter_revision, 5)

        disconnected_spy = QSignalSpy(self.controller.disconnected)
        self.assertTrue(self.controller.disconnect())
        self.wait_for_signal(disconnected_spy)
        self.assertIsNone(self.transport.connected_address)

    def test_link_loss_during_session_read_never_reports_connected(self):
        """Close the connect-completion race without publishing false readiness."""
        self.transport.disconnect_during_session_read = True
        self.transport._devices = True
        connected_spy = QSignalSpy(self.controller.connection_succeeded)
        disconnected_spy = QSignalSpy(self.controller.disconnected)

        self.assertTrue(self.controller.connect("AA:BB:CC:DD:EE:FF"))
        self.wait_for_signal(disconnected_spy)

        self.assertEqual(connected_spy.count(), 0)

    def test_loads_a_prescription_through_one_controller_operation(self):
        """Publish progress and completion for the reusable loading pipeline."""
        session_spy = QSignalSpy(self.controller.session_loaded)
        self.assertTrue(self.controller.connect("AA:BB:CC:DD:EE:FF"))
        self.wait_for_signal(session_spy)
        progress_spy = QSignalSpy(self.controller.prescription_load_progress)
        loaded_spy = QSignalSpy(self.controller.prescription_loaded)

        self.assertTrue(self.controller.load_prescription(N1_PRESCRIPTION))
        self.wait_for_signal(loaded_spy)

        result = loaded_spy.at(0)[0]
        self.assertIsInstance(result, PrescriptionLoadResult)
        self.assertEqual(result.profile_id, "N1")
        self.assertEqual(progress_spy.count(), 11)
        self.assertEqual(
            [parameter_id for parameter_id, _ in self.transport.parameter_writes],
            list(range(3, 14)),
        )


if __name__ == "__main__":
    unittest.main()
