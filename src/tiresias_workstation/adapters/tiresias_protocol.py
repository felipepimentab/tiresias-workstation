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
_REQUEST = struct.Struct("<BBIBBi")
_RESPONSE = struct.Struct("<BBIBBiI")

_PROTOCOL_MAJOR = 3
_GET_PARAMETER = 1
_SET_PARAMETER = 2


class TiresiasProtocolClient:
    """Expose high-level Tiresias operations over a loop-owned transport.

    Args:
        transport: Connected-device transport responsible only for BLE and
            generic GATT mechanics.
        response_timeout: Maximum wait for each correlated word response, in
            seconds.
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
        """Read all words of one fixed-contract parameter."""
        definition = self._definition(parameter_id)
        words, revision = await self._exchange_words(
            _GET_PARAMETER,
            parameter_id,
            (0,) * definition.word_count,
        )
        return ParameterValue(parameter_id, words, revision)

    async def write_parameter(self, parameter_id: int, value: int) -> ParameterValue:
        """Persist one validated scalar and return its committed revision."""
        definition = self._definition(parameter_id)
        if not definition.writable:
            raise ValueError(f"Parameter {parameter_id} is read-only.")
        if not definition.accepts(value):
            raise ValueError(
                f"Value must be {definition.minimum}..{definition.maximum} "
                f"in steps of {definition.step}."
            )
        words, revision = await self._exchange_words(
            _SET_PARAMETER,
            parameter_id,
            (value,),
        )
        return ParameterValue(parameter_id, words, revision)

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

    async def _exchange_words(
        self,
        opcode: int,
        parameter_id: int,
        request_values: tuple[int, ...],
    ) -> tuple[tuple[int, ...], int]:
        """Serialize one or more indexed word requests under one subscription."""
        async with self._request_lock:
            return await self._exchange_words_serialized(
                opcode,
                parameter_id,
                request_values,
            )

    async def _exchange_words_serialized(
        self,
        opcode: int,
        parameter_id: int,
        request_values: tuple[int, ...],
    ) -> tuple[tuple[int, ...], int]:
        """Exchange indexed words while owning the protocol operation slot."""
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[
            tuple[int, RequestResult, int, int, int, int, int]
        ] | None = None
        expected_transaction_id = 0

        def response_received(payload: bytes) -> None:
            """Accept only the indication correlated to the active word."""
            nonlocal response_future
            try:
                response = decode_response(payload)
            except ProtocolError as error:
                if response_future is not None and not response_future.done():
                    response_future.set_exception(error)
                return
            if (
                response[2] == expected_transaction_id
                and response_future is not None
                and not response_future.done()
            ):
                response_future.set_result(response)

        words: list[int] = []
        revisions: set[int] = set()
        await self._transport.start_notifications(RESPONSE_UUID, response_received)
        try:
            for word_index, request_value in enumerate(request_values):
                expected_transaction_id = self._allocate_transaction_id()
                response_future = loop.create_future()
                payload = _REQUEST.pack(
                    opcode,
                    0,
                    expected_transaction_id,
                    parameter_id,
                    word_index,
                    request_value,
                )
                await self._transport.write_characteristic(
                    REQUEST_UUID,
                    payload,
                    response=True,
                )
                try:
                    response = await asyncio.wait_for(
                        response_future,
                        timeout=self._response_timeout,
                    )
                except TimeoutError as error:
                    raise TimeoutError(
                        "The device did not return a parameter result."
                    ) from error

                (
                    response_opcode,
                    result,
                    _,
                    response_id,
                    response_word_index,
                    response_value,
                    revision,
                ) = response
                if (
                    response_opcode != opcode
                    or response_id != parameter_id
                    or response_word_index != word_index
                ):
                    raise ProtocolError(
                        "The correlated response does not match the request."
                    )
                if result is not RequestResult.OK:
                    raise RequestError(result, parameter_id)
                words.append(response_value)
                revisions.add(revision)
        finally:
            await self._transport.stop_notifications(RESPONSE_UUID)

        if len(revisions) != 1:
            raise ProtocolError("Parameter revision changed during a multi-word read.")
        return tuple(words), revisions.pop()

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
    if maximum_request < _REQUEST.size or maximum_response < _RESPONSE.size:
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
        word_index,
        tail,
    ) = _STATUS.unpack(payload)
    if reserved != 0 or tail != 0 or flags & ~0x07:
        raise ProtocolError("Status contains nonzero reserved data.")
    try:
        return DeviceStatus(
            DeviceState(state),
            StatusFlag(flags),
            RequestResult(result),
            revision,
            transaction_id,
            parameter_id,
            word_index,
        )
    except ValueError as error:
        raise ProtocolError("Status contains an unsupported enum value.") from error


def decode_response(
    payload: bytes,
) -> tuple[int, RequestResult, int, int, int, int, int]:
    """Decode one fixed 16-byte correlated word response."""
    if len(payload) != _RESPONSE.size:
        raise ProtocolError("Parameter response must be 16 bytes.")
    (
        opcode,
        raw_result,
        transaction_id,
        parameter_id,
        word_index,
        value,
        revision,
    ) = _RESPONSE.unpack(payload)
    if opcode not in (_GET_PARAMETER, _SET_PARAMETER):
        raise ProtocolError("Parameter response has an invalid opcode.")
    try:
        result = RequestResult(raw_result)
    except ValueError as error:
        raise ProtocolError("Parameter response has an invalid result.") from error
    return (
        opcode,
        result,
        transaction_id,
        parameter_id,
        word_index,
        value,
        revision,
    )
