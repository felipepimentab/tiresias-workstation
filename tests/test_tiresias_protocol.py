"""Exercise the fixed Tiresias packet contract without Bluetooth hardware."""

import struct
import unittest

from tiresias_workstation.adapters.tiresias_protocol import (
    FIRMWARE_REVISION_UUID,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER_UUID,
    PROTOCOL_INFO_UUID,
    REQUEST_UUID,
    STATUS_UUID,
    TIRESIAS_SERVICE_UUID,
    TiresiasProtocolClient,
    decode_protocol_information,
)
from tiresias_workstation.domain.devices import DiscoveredDevice
from tiresias_workstation.domain.dsp_contract import (
    DSP_PARAMETER_CONTRACT_CRC32,
    DSP_PARAMETERS,
)
from tiresias_workstation.domain.tiresias import ProtocolError, RequestError


class FakeGattTransport:
    """Model GATT characteristic access and synchronous indications."""

    def __init__(self) -> None:
        """Create a valid connected service image."""
        self.values = {
            MANUFACTURER_NAME_UUID: b"Tiresias",
            MODEL_NUMBER_UUID: b"Tiresias DK",
            FIRMWARE_REVISION_UUID: b"0.1.0",
            PROTOCOL_INFO_UUID: struct.pack(
                "<BBHIHHIII",
                4,
                0,
                24,
                15,
                12,
                16,
                DSP_PARAMETER_CONTRACT_CRC32,
                42,
                3,
            ),
            STATUS_UUID: struct.pack("<BBBBIIBBH", 3, 7, 0, 0, 3, 0, 0, 0, 0),
        }
        self.callback = None
        self.result = 0
        self.emit_response = True
        self.advance_write_revision = False
        self.last_write = None
        self.writes: list[bytes] = []
        self.reads: list[str] = []
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
        self.reads.append(characteristic_uuid)
        if characteristic_uuid not in self.values:
            raise RuntimeError("not present")
        return self.values[characteristic_uuid]

    async def write_characteristic(self, characteristic_uuid, value, *, response):
        self.last_write = (characteristic_uuid, value, response)
        self.writes.append(value)
        (
            opcode,
            _flags,
            transaction_id,
            parameter_id,
            byte_offset,
            request_data,
        ) = struct.unpack("<BBIBB4s", value)
        response_data = (
            bytes((byte_offset + index) & 0xFF for index in range(4))
            if opcode == 1
            else request_data
        )
        revision = (
            4 + byte_offset // 4
            if opcode == 2 and self.advance_write_revision
            else 4
        )
        payload = struct.pack(
            "<BBIBB4sI",
            opcode,
            self.result,
            transaction_id,
            parameter_id,
            byte_offset,
            response_data,
            revision,
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
    """Verify fixed-contract checks and indexed parameter operations."""

    async def asyncSetUp(self):
        self.transport = FakeGattTransport()
        self.client = TiresiasProtocolClient(self.transport, response_timeout=0.1)

    async def test_reads_identity_protocol_status_and_fixed_contract(self):
        """Return a session without reading dynamic catalog metadata."""
        session = await self.client.read_session()

        self.assertEqual(session.information.manufacturer, "Tiresias")
        self.assertEqual(session.information.model_number, "Tiresias DK")
        self.assertEqual(session.information.firmware_revision, "0.1.0")
        self.assertEqual(session.protocol.boot_id, 42)
        self.assertEqual(session.status.parameter_revision, 3)
        self.assertEqual(len(session.parameters), 15)
        self.assertEqual(session.parameters[2].name, "LUT")
        self.assertEqual(session.parameters[2].byte_count, 136)
        self.assertEqual(len(self.transport.reads), 7)
        self.assertIn(PROTOCOL_INFO_UUID, self.transport.reads)
        self.assertIn(STATUS_UUID, self.transport.reads)

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

    async def test_reads_every_byte_chunk_of_a_lut_by_offset(self):
        """Assemble one opaque byte array from correlated chunk responses."""
        reading = await self.client.read_parameter(3)

        requests = [struct.unpack("<BBIBB4s", payload) for payload in self.transport.writes]
        self.assertEqual(len(reading.data), 136)
        self.assertEqual(reading.data[:4], b"\x00\x01\x02\x03")
        self.assertEqual(reading.data[-4:], b"\x84\x85\x86\x87")
        self.assertEqual([request[4] for request in requests], list(range(0, 136, 4)))
        self.assertTrue(all(request[3] == 3 for request in requests))
        self.assertIsNone(self.transport.callback)

    async def test_correlates_byte_array_get_and_persistent_set(self):
        """Use stable byte IDs and report firmware-confirmed revisions."""
        reading = await self.client.read_parameter(11)
        written = await self.client.write_parameter(11, b"\x01\x00\x00\x00")

        self.assertEqual(reading.data, b"\x00\x01\x02\x03")
        self.assertEqual(written.data, b"\x01\x00\x00\x00")
        self.assertEqual(written.parameter_revision, 4)
        uuid, payload, with_response = self.transport.last_write
        self.assertEqual(uuid, REQUEST_UUID)
        self.assertTrue(with_response)
        self.assertEqual(
            struct.unpack("<BBIBB4s", payload)[3:],
            (11, 0, b"\x01\x00\x00\x00"),
        )

    async def test_accepts_revision_advances_during_multi_chunk_write(self):
        """Return the final revision when firmware commits each LUT chunk."""
        self.transport.advance_write_revision = True
        data = bytes(range(136))

        written = await self.client.write_parameter(3, data)

        self.assertEqual(written.data, data)
        self.assertEqual(written.parameter_revision, 37)

    async def test_surfaces_device_rejection(self):
        """Translate a terminal firmware result into an actionable error."""
        self.transport.result = 6

        with self.assertRaisesRegex(RequestError, "persist failed"):
            await self.client.write_parameter(11, b"\x01\x00\x00\x00")

    async def test_att_write_response_is_not_operation_completion(self):
        """Require the correlated terminal indication after an ATT write."""
        self.transport.emit_response = False

        with self.assertRaisesRegex(TimeoutError, "parameter result"):
            await self.client.write_parameter(11, b"\x01\x00\x00\x00")

    def test_rejects_contract_mismatch(self):
        """Fail the handshake when the catalog fingerprint differs."""
        fields = list(
            struct.unpack(
                "<BBHIHHIII",
                self.transport.values[PROTOCOL_INFO_UUID],
            )
        )
        fields[6] ^= 1
        payload = struct.pack("<BBHIHHIII", *fields)

        with self.assertRaisesRegex(ProtocolError, "incompatible DSP"):
            decode_protocol_information(payload)


if __name__ == "__main__":
    unittest.main()
