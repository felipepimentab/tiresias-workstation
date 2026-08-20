"""Exercise Tiresias packet validation and correlation without Bluetooth."""

import struct
import unittest
import zlib

from tiresias_workstation.adapters.tiresias_protocol import (
    CATALOG_UUID,
    FIRMWARE_REVISION_UUID,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER_UUID,
    PROTOCOL_INFO_UUID,
    REQUEST_UUID,
    RESPONSE_UUID,
    STATUS_UUID,
    TIRESIAS_SERVICE_UUID,
    TiresiasProtocolClient,
    decode_catalog,
)
from tiresias_workstation.domain.devices import DiscoveredDevice
from tiresias_workstation.domain.tiresias import (
    ParameterAccess,
    ProtocolError,
    RequestError,
)


def catalog_value() -> tuple[bytes, int]:
    """Build one valid catalog value and return its entries CRC."""
    entry = struct.pack(
        "<HBBHBBiiii8s",
        1,
        7,
        1,
        0x2000,
        1,
        1,
        0,
        0x02000000,
        0x00800000,
        0x00008000,
        b"PHASE1\0\0",
    )
    crc = zlib.crc32(entry) & 0xFFFFFFFF
    header = struct.pack("<BBHHHII", 1, 32, 1, 48, 0, 0x17870001, crc)
    return header + entry, crc


class FakeGattTransport:
    """Model GATT characteristic access and synchronous indications."""

    def __init__(self) -> None:
        """Create a valid connected service image."""
        catalog, crc = catalog_value()
        self.values = {
            MANUFACTURER_NAME_UUID: b"Tiresias",
            MODEL_NUMBER_UUID: b"Tiresias DK",
            FIRMWARE_REVISION_UUID: b"0.1.0",
            PROTOCOL_INFO_UUID: struct.pack(
                "<BBHIHHHHIIII",
                1,
                0,
                32,
                15,
                12,
                16,
                32,
                1,
                0x17870001,
                crc,
                42,
                3,
            ),
            CATALOG_UUID: catalog,
            STATUS_UUID: struct.pack("<BBBBIIHH", 3, 7, 0, 0, 3, 0, 0, 0),
        }
        self.callback = None
        self.result = 0
        self.emit_response = True
        self.last_write = None
        self.scan_result = []

    async def scan(self, on_device, *, timeout):
        del timeout
        for device in self.scan_result:
            on_device(device)
        return self.scan_result

    async def connect(self, address, on_disconnected, *, timeout):
        del address, on_disconnected, timeout

    async def disconnect(self):
        pass

    async def read_characteristic(self, characteristic_uuid):
        if characteristic_uuid not in self.values:
            raise RuntimeError("not present")
        return self.values[characteristic_uuid]

    async def write_characteristic(self, characteristic_uuid, value, *, response):
        self.last_write = (characteristic_uuid, value, response)
        opcode, _flags, transaction_id, parameter_id, request_value = struct.unpack(
            "<BBIHi", value
        )
        response_value = 0x00800000 if opcode == 1 else request_value
        payload = struct.pack(
            "<BBIHiI",
            opcode,
            self.result,
            transaction_id,
            parameter_id,
            response_value,
            4,
        )
        if self.emit_response:
            self.callback(payload)

    async def start_notifications(self, characteristic_uuid, callback):
        self.assert_uuid = characteristic_uuid
        self.callback = callback

    async def stop_notifications(self, characteristic_uuid):
        self.assert_uuid = characteristic_uuid
        self.callback = None


class TiresiasProtocolClientTest(unittest.IsolatedAsyncioTestCase):
    """Verify decoding, session checks, and parameter operations."""

    async def asyncSetUp(self):
        self.transport = FakeGattTransport()
        self.client = TiresiasProtocolClient(self.transport, response_timeout=0.1)

    async def test_reads_identity_protocol_status_and_catalog(self):
        """Return one cross-validated session without exposing DSP addresses."""
        session = await self.client.read_session()

        self.assertEqual(session.information.manufacturer, "Tiresias")
        self.assertEqual(session.information.model_number, "Tiresias DK")
        self.assertEqual(session.information.firmware_revision, "0.1.0")
        self.assertEqual(session.protocol.boot_id, 42)
        self.assertEqual(session.status.parameter_revision, 3)
        self.assertEqual(session.catalog[0].name, "PHASE1")
        self.assertEqual(session.catalog[0].step, 0x00008000)
        self.assertTrue(session.catalog[0].access & ParameterAccess.PERSISTENT)

    async def test_marks_service_uuid_without_relying_on_local_name(self):
        """Identify a supported board from its advertised service UUID."""
        self.transport.scan_result = [
            DiscoveredDevice(
                "AA:BB:CC:DD:EE:FF",
                None,
                -50,
                (TIRESIAS_SERVICE_UUID,),
            )
        ]
        updates = []

        devices = await self.client.scan(updates.append, timeout=0)

        self.assertTrue(devices[0].is_tiresias)
        self.assertTrue(updates[0].is_tiresias)

    async def test_correlates_get_and_persistent_set_responses(self):
        """Use stable IDs and report the firmware-confirmed revision."""
        await self.client.read_session()

        reading = await self.client.read_parameter(1)
        written = await self.client.write_parameter(1, 0x01000000)

        self.assertEqual(reading.value, 0x00800000)
        self.assertEqual(written.value, 0x01000000)
        self.assertEqual(written.parameter_revision, 4)
        uuid, payload, with_response = self.transport.last_write
        self.assertEqual(uuid, REQUEST_UUID)
        self.assertTrue(with_response)
        self.assertEqual(struct.unpack("<BBIHi", payload)[3:], (1, 0x01000000))

    async def test_surfaces_device_rejection(self):
        """Translate a terminal firmware result into an actionable error."""
        await self.client.read_session()
        self.transport.result = 6

        with self.assertRaisesRegex(RequestError, "persist failed"):
            await self.client.write_parameter(1, 0x01000000)

    async def test_att_write_response_is_not_treated_as_persistence(self):
        """Require the correlated terminal indication after an accepted write."""
        await self.client.read_session()
        self.transport.emit_response = False

        with self.assertRaisesRegex(TimeoutError, "parameter result"):
            await self.client.write_parameter(1, 0x01000000)

    def test_rejects_catalog_integrity_failure(self):
        """Reject a catalog whose payload changed after CRC generation."""
        payload, _crc = catalog_value()
        corrupted = payload[:-1] + bytes([payload[-1] ^ 1])

        with self.assertRaisesRegex(ProtocolError, "integrity"):
            decode_catalog(corrupted)

    def test_matches_firmware_catalog_golden_crc(self):
        """Pin the complete firmware V1 catalog byte representation."""
        addresses = (10348, 10352, 10356, 10360)
        names = (b"gain_1", b"gain_2", b"gain_3", b"headroom")
        entries = b"".join(
            struct.pack(
                "<HBBHBBiiii8s",
                parameter_id,
                15,
                1,
                address,
                1,
                1,
                0,
                0x02000000,
                0x00800000,
                0x00008000,
                name.ljust(8, b"\0"),
            )
            for parameter_id, address, name in zip(
                range(1, 5), addresses, names, strict=True
            )
        )
        crc = zlib.crc32(entries) & 0xFFFFFFFF
        payload = struct.pack(
            "<BBHHHII", 1, 32, 4, 144, 0, 0x54525031, crc
        ) + entries

        catalog = decode_catalog(
            payload,
            expected_layout_id=0x54525031,
            expected_crc32=0xDFAC5B27,
        )

        self.assertEqual(crc, 0xDFAC5B27)
        self.assertEqual([entry.name for entry in catalog], [
            "gain_1", "gain_2", "gain_3", "headroom"
        ])


if __name__ == "__main__":
    unittest.main()
