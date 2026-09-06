"""Implement the fixed Tiresias GATT contract over a generic BLE transport.

All service UUIDs, binary layouts, compatibility checks, correlation, and
response handling live here. Application and presentation code consume domain
models and never construct protocol packets.
"""

import asyncio
import struct
from collections.abc import Callable
from dataclasses import replace

from tiresias_workstation.domain.devices import DeviceTransport, DiscoveredDevice
from tiresias_workstation.domain.dsp_contract import (
    DSP_PARAMETER_CONTRACT_CRC32,
    DSP_PARAMETERS,
    DSP_PARAMETERS_BY_ID,
    DspParameterDefinition,
)
from tiresias_workstation.domain.tiresias import (
    DeviceInformation,
    DeviceSession,
    DeviceState,
    DeviceStatus,
    ParameterValue,
    ProtocolCapability,
    ProtocolError,
    ProtocolInformation,
    RequestError,
    RequestResult,
    StatusFlag,
)

TIRESIAS_SERVICE_UUID = "7b9a0001-6e4f-4b2d-a9c8-4f2e6f5d1000"
PROTOCOL_INFO_UUID = "7b9a0002-6e4f-4b2d-a9c8-4f2e6f5d1000"
STATUS_UUID = "7b9a0004-6e4f-4b2d-a9c8-4f2e6f5d1000"
REQUEST_UUID = "7b9a0005-6e4f-4b2d-a9c8-4f2e6f5d1000"
RESPONSE_UUID = "7b9a0006-6e4f-4b2d-a9c8-4f2e6f5d1000"

MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

_PROTOCOL_INFO = struct.Struct("<BBHIHHIII")
_STATUS = struct.Struct("<BBBBIIBBH")
_REQUEST = struct.Struct("<BBIBB")
_RESPONSE = struct.Struct("<BBIBBI")

_PROTOCOL_MAJOR = 5
_MAX_PARAMETER_SIZE = max(parameter.byte_count for parameter in DSP_PARAMETERS)
_GET_PARAMETER = 1
_SET_PARAMETER = 2


class TiresiasProtocolClient:
    """Expose high-level Tiresias operations over a loop-owned transport.

    Args:
        transport: Connected-device transport responsible only for BLE and
            generic GATT mechanics.
        response_timeout: Deadline for each parameter exchange, in seconds.
            Subscription teardown is separately bounded to one second.
    """

    def __init__(
        self,
        transport: DeviceTransport,
        *,
        response_timeout: float = 5.0,
    ) -> None:
        """Initialize protocol state without accessing Bluetooth."""
        self._transport = transport
        self._response_timeout = response_timeout
        self._next_transaction_id = 1
        self._request_lock = asyncio.Lock()

    async def scan(
        self,
        on_device: Callable[[DiscoveredDevice], None],
        *,
        timeout: float,
    ) -> list[DiscoveredDevice]:
        """Discover devices and mark custom-service advertisements by UUID."""

        def mark_device(device: DiscoveredDevice) -> DiscoveredDevice:
            marked = replace(
                device,
                is_tiresias=TIRESIAS_SERVICE_UUID in device.service_uuids,
            )
            on_device(marked)
            return marked

        devices: list[DiscoveredDevice] = []
        reported: dict[str, DiscoveredDevice] = {}

        def device_received(device: DiscoveredDevice) -> None:
            reported[device.address] = mark_device(device)

        raw_devices = await self._transport.scan(device_received, timeout=timeout)
        for device in raw_devices:
            marked = reported.get(device.address)
            devices.append(
                marked
                if marked is not None
                else replace(
                    device,
                    is_tiresias=TIRESIAS_SERVICE_UUID in device.service_uuids,
                )
            )
        return devices

    async def connect(
        self,
        address: str,
        on_disconnected: Callable[[str], None],
        *,
        timeout: float,
    ) -> None:
        """Delegate connection establishment to the BLE transport."""
        await self._transport.connect(address, on_disconnected, timeout=timeout)

    async def disconnect(self) -> None:
        """Disconnect the active transport."""
        await self._transport.disconnect()

    async def read_session(self) -> DeviceSession:
        """Read and cross-validate identity, contract metadata, and status.

        Returns:
            Fully validated session snapshot for the connected board.

        Raises:
            ProtocolError: If firmware is incompatible or service values are
                malformed or internally inconsistent.
        """
        information = await self._read_device_information()
        protocol = decode_protocol_information(
            await self._transport.read_characteristic(PROTOCOL_INFO_UUID)
        )
        status = decode_status(await self._transport.read_characteristic(STATUS_UUID))

        if status.state is not DeviceState.READY:
            raise ProtocolError(f"Device is not ready (state {status.state.name}).")
        if not status.flags & StatusFlag.PARAMETERS_LOADED:
            raise ProtocolError(
                "Device parameter storage is not ready. Restart the board with "
                "current firmware and reconnect."
            )
        if protocol.parameter_revision != status.parameter_revision:
            raise ProtocolError("Protocol Information and Status revision disagree.")
        capability_deferred = bool(
            protocol.capabilities & ProtocolCapability.DSP_APPLY_DEFERRED
        )
        status_deferred = bool(status.flags & StatusFlag.DSP_APPLY_DEFERRED)
        if capability_deferred != status_deferred:
            raise ProtocolError("DSP deferred-apply capability and status disagree.")
        return DeviceSession(information, protocol, status, DSP_PARAMETERS)

    async def read_parameter(self, parameter_id: int) -> ParameterValue:
        """Read all opaque bytes of one fixed-contract parameter."""
        definition = self._definition(parameter_id)
        data, revision = await self._exchange_bytes(
            _GET_PARAMETER,
            parameter_id,
            bytes(definition.byte_count),
        )
        return ParameterValue(parameter_id, data, revision)

    async def write_parameter(self, parameter_id: int, data: bytes) -> ParameterValue:
        """Persist one validated opaque byte array and return its revision."""
        definition = self._definition(parameter_id)
        if not definition.writable:
            raise ValueError(f"Parameter {parameter_id} is read-only.")
        if not definition.accepts(data):
            raise ValueError(f"Parameter {parameter_id} requires {definition.byte_count} bytes.")
        response_data, revision = await self._exchange_bytes(
            _SET_PARAMETER,
            parameter_id,
            data,
        )
        return ParameterValue(parameter_id, response_data, revision)

    async def _read_device_information(self) -> DeviceInformation:
        """Read optional standard DIS text fields independently."""
        return DeviceInformation(
            manufacturer=await self._read_optional_text(MANUFACTURER_NAME_UUID),
            model_number=await self._read_optional_text(MODEL_NUMBER_UUID),
            serial_number=await self._read_optional_text(SERIAL_NUMBER_UUID),
            hardware_revision=await self._read_optional_text(HARDWARE_REVISION_UUID),
            firmware_revision=await self._read_optional_text(FIRMWARE_REVISION_UUID),
        )

    async def _read_optional_text(self, characteristic_uuid: str) -> str | None:
        """Decode one optional UTF-8 DIS field, tolerating absent fields."""
        try:
            value = await self._transport.read_characteristic(characteristic_uuid)
        except Exception:
            return None
        text = value.decode("utf-8", errors="replace").rstrip("\x00").strip()
        return text or None

    @staticmethod
    def _definition(parameter_id: int) -> DspParameterDefinition:
        """Return a fixed definition or reject an unknown identifier."""
        definition = DSP_PARAMETERS_BY_ID.get(parameter_id)
        if definition is None:
            raise ValueError(f"Parameter {parameter_id} is not in the fixed contract.")
        return definition

    async def _exchange_bytes(
        self,
        opcode: int,
        parameter_id: int,
        request_data: bytes,
    ) -> tuple[bytes, int]:
        """Serialize one complete parameter exchange under a bounded timeout."""
        async with self._request_lock:
            try:
                async with asyncio.timeout(self._response_timeout):
                    return await self._exchange_bytes_serialized(
                        opcode, parameter_id, request_data
                    )
            except TimeoutError as error:
                raise TimeoutError(
                    "The device did not return a parameter result. The complete "
                    "value may have committed; reconnect and read it before retrying."
                ) from error

    async def _exchange_bytes_serialized(
        self,
        opcode: int,
        parameter_id: int,
        request_data: bytes,
    ) -> tuple[bytes, int]:
        """Send one whole value and require its correlated terminal indication.

        A lost response leaves the commit outcome uncertain, but cannot leave a
        prefix of the parameter committed. No automatic SET retry is performed.
        """
        loop = asyncio.get_running_loop()
        transaction_id = self._allocate_transaction_id()
        response_future = loop.create_future()

        def response_received(payload: bytes) -> None:
            """Resolve the active operation only for its transaction identifier."""
            if response_future.done():
                return
            try:
                response = decode_response(payload)
            except ProtocolError as error:
                response_future.set_exception(error)
                return
            if response[2] == transaction_id:
                response_future.set_result(response)

        data = request_data if opcode == _SET_PARAMETER else b""
        payload = _REQUEST.pack(opcode, 0, transaction_id, parameter_id, len(data)) + data
        try:
            await self._transport.start_notifications(RESPONSE_UUID, response_received)
            await self._transport.write_characteristic(REQUEST_UUID, payload, response=True)
            response = await response_future
            response_opcode, result, _, response_id, response_data, revision = response
            if response_opcode != opcode or response_id != parameter_id:
                raise ProtocolError("The correlated response does not match the request.")
            if result is not RequestResult.OK:
                raise RequestError(result, parameter_id)
            if len(response_data) != len(request_data):
                raise ProtocolError("The response does not contain the complete parameter.")
            if opcode == _SET_PARAMETER and response_data != request_data:
                raise ProtocolError("The confirmed parameter differs from the requested value.")
            return response_data, revision
        finally:
            # A disconnect can also end a subscription. Preserve the original
            # operation failure if cleanup itself fails.
            response_future.cancel()
            try:
                await asyncio.wait_for(
                    self._transport.stop_notifications(RESPONSE_UUID), timeout=1.0
                )
            except Exception:
                pass

    def _allocate_transaction_id(self) -> int:
        """Return a nonzero 32-bit transaction identifier for this process."""
        transaction_id = self._next_transaction_id
        self._next_transaction_id = (transaction_id + 1) & 0xFFFFFFFF
        if self._next_transaction_id == 0:
            self._next_transaction_id = 1
        return transaction_id


def decode_protocol_information(payload: bytes) -> ProtocolInformation:
    """Decode and validate fixed-contract Protocol Information."""
    if len(payload) != _PROTOCOL_INFO.size:
        raise ProtocolError(
            f"Protocol Information must be {_PROTOCOL_INFO.size} bytes."
        )
    (
        major,
        minor,
        length,
        capabilities,
        maximum_request,
        maximum_response,
        contract_crc32,
        boot_id,
        revision,
    ) = _PROTOCOL_INFO.unpack(payload)
    if major != _PROTOCOL_MAJOR or length != _PROTOCOL_INFO.size:
        raise ProtocolError(f"Unsupported Tiresias protocol {major}.{minor}.")
    if (
        maximum_request < _REQUEST.size + _MAX_PARAMETER_SIZE
        or maximum_response < _RESPONSE.size + _MAX_PARAMETER_SIZE
    ):
        raise ProtocolError("Device request or response capacity is too small.")
    if contract_crc32 != DSP_PARAMETER_CONTRACT_CRC32:
        raise ProtocolError("Device uses an incompatible DSP parameter contract.")
    required = (
        ProtocolCapability.GET_PARAMETER
        | ProtocolCapability.SET_PARAMETER
        | ProtocolCapability.PERSISTENCE
    )
    if capabilities & ~0x0F:
        raise ProtocolError("Protocol Information has unknown capabilities.")
    parsed_capabilities = ProtocolCapability(capabilities)
    if parsed_capabilities & required != required:
        raise ProtocolError("Device lacks required parameter capabilities.")
    return ProtocolInformation(
        major,
        minor,
        parsed_capabilities,
        maximum_request,
        maximum_response,
        contract_crc32,
        boot_id,
        revision,
    )


def decode_status(payload: bytes) -> DeviceStatus:
    """Decode a fixed 16-byte coherent service Status snapshot."""
    if len(payload) != _STATUS.size:
        raise ProtocolError("Status must be 16 bytes.")
    (
        state,
        flags,
        result,
        reserved,
        revision,
        transaction_id,
        parameter_id,
        byte_offset,
        tail,
    ) = _STATUS.unpack(payload)
    if reserved != 0 or tail != 0 or byte_offset != 0 or flags & ~0x07:
        raise ProtocolError("Status contains nonzero reserved data.")
    try:
        return DeviceStatus(
            DeviceState(state),
            StatusFlag(flags),
            RequestResult(result),
            revision,
            transaction_id,
            parameter_id,
            byte_offset,
        )
    except ValueError as error:
        raise ProtocolError("Status contains an unsupported enum value.") from error


def decode_response(
    payload: bytes,
) -> tuple[int, RequestResult, int, int, bytes, int]:
    """Decode a v5 whole-parameter response, rejecting partial or trailing data."""
    if not _RESPONSE.size <= len(payload) <= _RESPONSE.size + _MAX_PARAMETER_SIZE:
        raise ProtocolError("Parameter response has an invalid length.")
    opcode, raw_result, transaction_id, parameter_id, length, revision = (
        _RESPONSE.unpack_from(payload)
    )
    if len(payload) != _RESPONSE.size + length:
        raise ProtocolError("Parameter response length does not match its payload.")
    if opcode not in (_GET_PARAMETER, _SET_PARAMETER) or transaction_id == 0:
        raise ProtocolError("Parameter response has an invalid opcode or transaction.")
    try:
        result = RequestResult(raw_result)
    except ValueError as error:
        raise ProtocolError("Parameter response has an invalid result.") from error
    if result is not RequestResult.OK and length != 0:
        raise ProtocolError("Failed parameter response must not contain value data.")
    return opcode, result, transaction_id, parameter_id, payload[_RESPONSE.size:], revision
