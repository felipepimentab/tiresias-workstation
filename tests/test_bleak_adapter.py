"""Test Bleak adaptation without accessing an operating-system BLE adapter."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tiresias_workstation.bleak_adapter import BleakDeviceTransport


class FakeScanner:
    """Emit two advertisements for one device during async context entry."""

    def __init__(self, detection_callback):
        self.detection_callback = detection_callback

    async def __aenter__(self):
        device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name=None)
        first_advertisement = SimpleNamespace(
            local_name="Tiresias DK",
            rssi=-61,
            service_uuids=["0000180F-0000-1000-8000-00805F9B34FB"],
        )
        updated_advertisement = SimpleNamespace(
            local_name="Tiresias DK",
            rssi=-48,
            service_uuids=["0000180F-0000-1000-8000-00805F9B34FB"],
        )
        self.detection_callback(device, first_advertisement)
        self.detection_callback(device, updated_advertisement)
        return self

    async def __aexit__(self, exception_type, exception, traceback):
        return False


class FakeClient:
    """Model the subset of BleakClient used by the transport."""

    def __init__(self, device, disconnected_callback, timeout):
        self.device = device
        self.disconnected_callback = disconnected_callback
        self.timeout = timeout
        self.is_connected = False

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnected_callback(self)


class BleakDeviceTransportTest(unittest.IsolatedAsyncioTestCase):
    """Verify native-object retention and domain snapshot normalization."""

    async def test_scan_retains_latest_advertisement_and_connects_device(self):
        """Use the newest advertisement and reconnect through its native handle."""
        transport = BleakDeviceTransport()
        updates = []
        disconnected = []

        with (
            patch("tiresias_workstation.bleak_adapter.BleakScanner", FakeScanner),
            patch("tiresias_workstation.bleak_adapter.BleakClient", FakeClient),
        ):
            devices = await transport.scan(updates.append, timeout=0)
            await transport.connect(
                devices[0].address,
                disconnected.append,
                timeout=0.1,
            )
            await transport.disconnect()

        self.assertEqual(len(updates), 2)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "Tiresias DK")
        self.assertEqual(devices[0].rssi, -48)
        self.assertEqual(
            devices[0].service_uuids,
            ("0000180f-0000-1000-8000-00805f9b34fb",),
        )
        self.assertEqual(disconnected, [devices[0].address])

    async def test_connect_requires_a_recently_discovered_device(self):
        """Reject addresses that do not have a retained native device handle."""
        transport = BleakDeviceTransport()

        with self.assertRaisesRegex(ValueError, "Scan again"):
            await transport.connect("missing", lambda _address: None, timeout=0.1)


if __name__ == "__main__":
    unittest.main()
