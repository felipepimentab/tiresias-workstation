"""Exercise the fixed Tiresias packet contract without Bluetooth hardware."""

import asyncio
import struct
import unittest

from tiresias_workstation.adapters.tiresias_protocol import (
    FIRMWARE_REVISION_UUID,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER_UUID,
    PROTOCOL_INFO_UUID,
    REQUEST_UUID,
    STATUS_UUID,
    SYSTEM_COMMAND_UUID,
    SYSTEM_STATUS_UUID,
    TIRESIAS_SERVICE_UUID,
    TiresiasProtocolClient,
    decode_protocol_information,
    decode_response,
    decode_system_status,
)
from tiresias_workstation.domain.devices import DiscoveredDevice
from tiresias_workstation.domain.dsp_contract import (
    DSP_PARAMETER_CONTRACT_CRC32,
    DSP_PARAMETERS,
)
from tiresias_workstation.domain.tiresias import BoardCommand, ProtocolError, RequestError


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
                6,
                0,
                24,
                15,
                188,
                192,
                DSP_PARAMETER_CONTRACT_CRC32,
                42,
                3,
            ),
            STATUS_UUID: struct.pack("<BBBBIIBBH", 3, 7, 0, 0, 3, 0, 0, 0, 0),
            SYSTEM_STATUS_UUID: bytes((1, 2, 3, 0, 2, 0, 0, 0)),
        }
        self.callback = None
        self.status_callback = None
        self.result = 0
        self.emit_response = True
        self.write_delay = 0
        self.response_override = None
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
        await asyncio.sleep(self.write_delay)
        if characteristic_uuid == SYSTEM_COMMAND_UUID:
            return
        opcode, _flags, transaction_id, parameter_id, length = struct.unpack_from("<BBIBB", value)
        request_data = value[8:]
        if len(request_data) != length:
            raise AssertionError("Invalid request payload length")
        byte_count = DSP_PARAMETERS[parameter_id - 1].byte_count
        if opcode == 2 and length != byte_count:
            raise AssertionError("SET must contain the complete parameter")
        if opcode == 1 and length != 0:
            raise AssertionError("GET must not contain data")
        response_data = bytes(range(byte_count)) if opcode == 1 else request_data
        if self.result:
            response_data = b""
        payload = struct.pack(
            "<BBIBBI", opcode, self.result, transaction_id,
            parameter_id, len(response_data), 4,
        ) + response_data
        if self.response_override is not None:
            payload = self.response_override(payload)
        if self.emit_response:
            self.callback(payload)

    async def start_notifications(self, characteristic_uuid, callback):
        self.assert_uuid = characteristic_uuid
        if characteristic_uuid == SYSTEM_STATUS_UUID:
            self.status_callback = callback
        else:
            self.callback = callback

    async def stop_notifications(self, characteristic_uuid):
        self.assert_uuid = characteristic_uuid
        if characteristic_uuid == SYSTEM_STATUS_UUID:
            self.status_callback = None
        else:
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
        self.assertEqual(len(self.transport.reads), 8)
        self.assertIn(PROTOCOL_INFO_UUID, self.transport.reads)
        self.assertIn(STATUS_UUID, self.transport.reads)
        self.assertEqual(session.system_status.device.name, "OPERATIONAL")

    async def test_system_status_notifications_and_commands(self):
        """Decode status changes and send one typed board command."""
        received = []

        await self.client.watch_system_status(received.append)
        self.transport.status_callback(bytes((1, 2, 3, 5, 3, 0, 0, 0)))
        await self.client.send_board_command(BoardCommand.SELECT_LOCAL)

        self.assertEqual(received[0].codec.name, "LOCAL_ONLY")
        self.assertEqual(received[1].streaming.name, "STREAMING")
        self.assertEqual(
            self.transport.last_write,
            (SYSTEM_COMMAND_UUID, bytes((BoardCommand.SELECT_LOCAL,)), True),
        )
        with self.assertRaises(ProtocolError):
            decode_system_status(bytes((2, 2, 3, 0, 2, 0, 0, 0)))

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

    async def test_reads_complete_lut_in_one_response(self):
        """Read a coherent full LUT using one request and one indication."""
        reading = await self.client.read_parameter(3)

        requests = [struct.unpack("<BBIBB", payload) for payload in self.transport.writes]
        self.assertEqual(len(reading.data), 136)
        self.assertEqual(reading.data[:4], b"\x00\x01\x02\x03")
        self.assertEqual(reading.data[-4:], b"\x84\x85\x86\x87")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][4], 0)
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
            struct.unpack_from("<BBIBB", payload)[3:],
            (11, 4),
        )

    async def test_writes_complete_lut_in_one_operation(self):
        """Send all 136 bytes together and receive one committed revision."""
        data = bytes(range(136))

        written = await self.client.write_parameter(3, data)

        self.assertEqual(written.data, data)
        self.assertEqual(written.parameter_revision, 4)
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(self.transport.writes[0][8:], data)

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

    async def test_rejects_partial_lut_before_writing(self):
        """Never send a prefix of a parameter as a SET."""
        with self.assertRaises(ValueError):
            await self.client.write_parameter(3, bytes(132))
        self.assertEqual(self.transport.writes, [])

    async def test_reads_largest_parameter(self):
        """Accept the complete 180-byte soft-clip table."""
        reading = await self.client.read_parameter(15)
        self.assertEqual(reading.data, bytes(range(180)))
        self.assertEqual(len(self.transport.writes), 1)

    async def test_writes_complete_softclip_output_parameter(self):
        """Carry the largest writable value in one 188-byte request."""
        data = bytes(range(180))
        written = await self.client.write_parameter(15, data)
        self.assertEqual(written.data, data)
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(len(self.transport.writes[0]), 188)

    async def test_rejects_truncated_response(self):
        """Do not treat a missing tail as successful completion."""
        self.transport.response_override = lambda payload: payload[:-1]
        with self.assertRaises(ProtocolError):
            await self.client.read_parameter(3)

    async def test_rejects_short_success_even_with_matching_length(self):
        """Check the contract size as well as the frame's declared size."""
        self.transport.response_override = lambda payload: payload[:7] + bytes([4]) + payload[8:16]
        with self.assertRaisesRegex(ProtocolError, "complete parameter"):
            await self.client.read_parameter(3)

    async def test_rejects_wrong_set_echo(self):
        """Require confirmation of the requested complete value."""
        self.transport.response_override = lambda payload: payload[:-1] + bytes([255])
        with self.assertRaisesRegex(ProtocolError, "differs"):
            await self.client.write_parameter(3, bytes(136))

    async def test_timeout_also_bounds_att_write(self):
        """A blocked transport write must release the operation slot."""
        self.transport.write_delay = 1
        with self.assertRaisesRegex(TimeoutError, "may have committed"):
            await self.client.write_parameter(3, bytes(136))
        self.assertIsNone(self.transport.callback)
        self.transport.write_delay = 0
        await self.client.read_parameter(3)

    async def test_wrong_transaction_cannot_complete_write(self):
        """A stale response must leave the operation waiting for its own result."""
        self.transport.response_override = lambda payload: payload[:2] + struct.pack("<I", 99) + payload[6:]
        with self.assertRaises(TimeoutError):
            await self.client.write_parameter(3, bytes(136))

    def test_rejects_v4(self):
        """Never send a whole-value SET to a chunk-based firmware."""
        payload = self.transport.values[PROTOCOL_INFO_UUID]
        with self.assertRaisesRegex(ProtocolError, "Unsupported"):
            decode_protocol_information(bytes([4]) + payload[1:])

    def test_rejects_trailing_response_data(self):
        """The response must have exactly its declared length."""
        with self.assertRaises(ProtocolError):
            decode_response(struct.pack("<BBIBBI", 1, 0, 1, 3, 0, 4) + b"extra")

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
