"""Implement the Tiresias GATT wire protocol over a generic BLE transport.

All service UUIDs, binary layouts, integrity checks, correlation, and response
handling live here. Application and presentation code consume domain models
and never construct protocol packets.
"""

import asyncio
import struct
import zlib
from collections.abc import Callable
from dataclasses import replace

from tiresias_workstation.domain.devices import DeviceTransport, DiscoveredDevice
from tiresias_workstation.domain.tiresias import (
    DeviceInformation,
    DeviceSession,
    DeviceState,
    DeviceStatus,
    ParameterAccess,
    ParameterDefinition,
    ParameterEncoding,
    ParameterUnit,
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
CATALOG_UUID = "7b9a0003-6e4f-4b2d-a9c8-4f2e6f5d1000"
STATUS_UUID = "7b9a0004-6e4f-4b2d-a9c8-4f2e6f5d1000"
REQUEST_UUID = "7b9a0005-6e4f-4b2d-a9c8-4f2e6f5d1000"
RESPONSE_UUID = "7b9a0006-6e4f-4b2d-a9c8-4f2e6f5d1000"

MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

_PROTOCOL_INFO = struct.Struct("<BBHIHHHHIIII")
_CATALOG_HEADER = struct.Struct("<BBHHHII")
_CATALOG_ENTRY = struct.Struct("<HBBHBBiiii8s")
_STATUS = struct.Struct("<BBBBIIHH")
_REQUEST = struct.Struct("<BBIHi")
_RESPONSE = struct.Struct("<BBIHiI")

_PROTOCOL_MAJOR = 1
_CATALOG_VERSION = 1
_GET_PARAMETER = 1
_SET_PARAMETER = 2


class TiresiasProtocolClient:
    """Expose high-level Tiresias operations over a loop-owned transport.

    Args:
        transport: Connected-device transport responsible only for BLE and
            generic GATT mechanics.
        response_timeout: Maximum wait for a correlated indication, in seconds.
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
        self._catalog: dict[int, ParameterDefinition] = {}
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
            devices.append(marked if marked is not None else replace(
                device,
                is_tiresias=TIRESIAS_SERVICE_UUID in device.service_uuids,
            ))
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
        """Disconnect and discard session-scoped catalog state."""
        try:
            await self._transport.disconnect()
        finally:
            self._catalog.clear()

    async def read_session(self) -> DeviceSession:
        """Read and cross-validate DIS, protocol metadata, status, and catalog.

        Returns:
            Fully validated session snapshot for the connected board.

        Raises:
            ProtocolError: If the firmware is incompatible or returns malformed
                or internally inconsistent service data.
        """
        information = await self._read_device_information()
        protocol = decode_protocol_information(
            await self._transport.read_characteristic(PROTOCOL_INFO_UUID)
        )
        catalog = decode_catalog(
            await self._transport.read_characteristic(CATALOG_UUID),
            expected_layout_id=protocol.layout_id,
            expected_crc32=protocol.catalog_crc32,
        )
        status = decode_status(await self._transport.read_characteristic(STATUS_UUID))

        if protocol.catalog_entry_size != _CATALOG_ENTRY.size:
            raise ProtocolError("Unsupported catalog entry size.")
        if protocol.catalog_count != len(catalog):
            raise ProtocolError("Protocol information and catalog count disagree.")
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
        self._catalog = {entry.parameter_id: entry for entry in catalog}
        return DeviceSession(information, protocol, status, catalog)

    async def read_parameter(self, parameter_id: int) -> ParameterValue:
        """Read one cataloged value with transaction correlation."""
        definition = self._definition(parameter_id)
        if not definition.access & ParameterAccess.READABLE:
            raise ValueError(f"Parameter {parameter_id} is not readable.")
        return await self._request(_GET_PARAMETER, parameter_id, 0)

    async def write_parameter(self, parameter_id: int, value: int) -> ParameterValue:
        """Persist one validated parameter and return the committed revision."""
        definition = self._definition(parameter_id)
        if not definition.access & ParameterAccess.WRITABLE:
            raise ValueError(f"Parameter {parameter_id} is read-only.")
        if not definition.accepts(value):
            raise ValueError(
                f"Value must be {definition.minimum}..{definition.maximum} "
                f"in steps of {definition.step}."
            )
        return await self._request(_SET_PARAMETER, parameter_id, value)

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

    def _definition(self, parameter_id: int) -> ParameterDefinition:
        """Return a session catalog entry or reject stale/unknown access."""
        definition = self._catalog.get(parameter_id)
        if definition is None:
            raise ValueError(f"Parameter {parameter_id} is not in this session catalog.")
        return definition

    async def _request(
        self,
        opcode: int,
        parameter_id: int,
        value: int,
    ) -> ParameterValue:
        """Serialize one request through its matching terminal indication."""
        async with self._request_lock:
            return await self._request_serialized(opcode, parameter_id, value)

    async def _request_serialized(
        self,
        opcode: int,
        parameter_id: int,
        value: int,
    ) -> ParameterValue:
        """Write one request while owning the protocol operation slot."""
        transaction_id = self._allocate_transaction_id()
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[tuple[int, RequestResult, int, int, int, int]] = (
            loop.create_future()
        )

        def response_received(payload: bytes) -> None:
            """Accept only the indication correlated to this request."""
            try:
                response = decode_response(payload)
            except ProtocolError as error:
                if not response_future.done():
                    response_future.set_exception(error)
                return
            if response[2] == transaction_id and not response_future.done():
                response_future.set_result(response)

        await self._transport.start_notifications(RESPONSE_UUID, response_received)
        try:
            payload = _REQUEST.pack(opcode, 0, transaction_id, parameter_id, value)
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
                raise TimeoutError("The device did not return a parameter result.") from error
        finally:
            await self._transport.stop_notifications(RESPONSE_UUID)

        response_opcode, result, _, response_id, response_value, revision = response
        if response_opcode != opcode or response_id != parameter_id:
            raise ProtocolError("The correlated response does not match the request.")
        if result is not RequestResult.OK:
            raise RequestError(result, parameter_id)
        return ParameterValue(parameter_id, response_value, revision)

    def _allocate_transaction_id(self) -> int:
        """Return a nonzero 32-bit transaction identifier for this process."""
        transaction_id = self._next_transaction_id
        self._next_transaction_id = (transaction_id + 1) & 0xFFFFFFFF
        if self._next_transaction_id == 0:
            self._next_transaction_id = 1
        return transaction_id


def decode_protocol_information(payload: bytes) -> ProtocolInformation:
    """Decode and validate the fixed 32-byte Protocol Information value."""
    if len(payload) != _PROTOCOL_INFO.size:
        raise ProtocolError("Protocol Information must be 32 bytes.")
    (
        major,
        minor,
        length,
        capabilities,
        maximum_request,
        maximum_response,
        entry_size,
        entry_count,
        layout_id,
        catalog_crc32,
        boot_id,
        revision,
    ) = _PROTOCOL_INFO.unpack(payload)
    if major != _PROTOCOL_MAJOR or length != _PROTOCOL_INFO.size:
        raise ProtocolError(f"Unsupported Tiresias protocol {major}.{minor}.")
    if maximum_request < _REQUEST.size or maximum_response < _RESPONSE.size:
        raise ProtocolError("Device request or response capacity is too small.")
    if entry_count == 0:
        raise ProtocolError("Device parameter catalog is empty.")
    required = (
        ProtocolCapability.GET_PARAMETER
        | ProtocolCapability.SET_PARAMETER
        | ProtocolCapability.PERSISTENCE
    )
    parsed_capabilities = ProtocolCapability(capabilities)
    if parsed_capabilities & required != required:
        raise ProtocolError("Device lacks required parameter persistence capabilities.")
    return ProtocolInformation(
        major,
        minor,
        parsed_capabilities,
        maximum_request,
        maximum_response,
        entry_size,
        entry_count,
        layout_id,
        catalog_crc32,
        boot_id,
        revision,
    )


def decode_catalog(
    payload: bytes,
    *,
    expected_layout_id: int | None = None,
    expected_crc32: int | None = None,
) -> tuple[ParameterDefinition, ...]:
    """Decode the bounded catalog and verify header, identity, and integrity.

    Args:
        payload: Complete catalog characteristic value.
        expected_layout_id: Optional Protocol Information layout identity.
        expected_crc32: Optional Protocol Information entries CRC.

    Returns:
        Validated immutable catalog entries.
    """
    if len(payload) < _CATALOG_HEADER.size:
        raise ProtocolError("Catalog header is truncated.")
    version, entry_size, count, total_length, reserved, layout_id, expected_crc = (
        _CATALOG_HEADER.unpack_from(payload)
    )
    expected_length = _CATALOG_HEADER.size + count * _CATALOG_ENTRY.size
    if (
        version != _CATALOG_VERSION
        or entry_size != _CATALOG_ENTRY.size
        or total_length != expected_length
        or len(payload) != expected_length
        or reserved != 0
    ):
        raise ProtocolError("Catalog header is invalid or incompatible.")
    entries_payload = payload[_CATALOG_HEADER.size :]
    if zlib.crc32(entries_payload) & 0xFFFFFFFF != expected_crc:
        raise ProtocolError("Catalog integrity check failed.")
    if expected_layout_id is not None and layout_id != expected_layout_id:
        raise ProtocolError("Protocol information and catalog layout disagree.")
    if expected_crc32 is not None and expected_crc != expected_crc32:
        raise ProtocolError("Protocol information and catalog CRC disagree.")

    entries = tuple(
        _decode_catalog_entry(entries_payload, offset)
        for offset in range(0, len(entries_payload), _CATALOG_ENTRY.size)
    )
    if len({entry.parameter_id for entry in entries}) != len(entries):
        raise ProtocolError("Catalog contains duplicate parameter identifiers.")
    return entries


def _decode_catalog_entry(payload: bytes, offset: int) -> ParameterDefinition:
    """Decode and validate one fixed-size catalog entry."""
    (
        parameter_id,
        access,
        encoding,
        dsp_address,
        word_count,
        unit,
        minimum,
        maximum,
        default,
        step,
        raw_name,
    ) = _CATALOG_ENTRY.unpack_from(payload, offset)
    try:
        if access & ~0x0F:
            raise ValueError
        parsed_access = ParameterAccess(access)
        parsed_encoding = ParameterEncoding(encoding)
        parsed_unit = ParameterUnit(unit)
    except ValueError as error:
        raise ProtocolError("Catalog contains an unsupported enum value.") from error
    try:
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise ProtocolError("Catalog parameter name is not ASCII.") from error
    if (
        parameter_id == 0
        or not name
        or word_count == 0
        or minimum > default
        or default > maximum
        or step <= 0
        or (default - minimum) % step != 0
    ):
        raise ProtocolError(f"Catalog entry {parameter_id} is invalid.")
    return ParameterDefinition(
        parameter_id,
        parsed_access,
        parsed_encoding,
        dsp_address,
        word_count,
        parsed_unit,
        minimum,
        maximum,
        default,
        step,
        name,
    )


def decode_status(payload: bytes) -> DeviceStatus:
    """Decode a fixed 16-byte coherent service Status snapshot."""
    if len(payload) != _STATUS.size:
        raise ProtocolError("Status must be 16 bytes.")
    state, flags, result, reserved, revision, transaction_id, parameter_id, tail = (
        _STATUS.unpack(payload)
    )
    if reserved != 0 or tail != 0:
        raise ProtocolError("Status reserved fields must be zero.")
    try:
        return DeviceStatus(
            DeviceState(state),
            StatusFlag(flags),
            RequestResult(result),
            revision,
            transaction_id,
            parameter_id,
        )
    except ValueError as error:
        raise ProtocolError("Status contains an unsupported enum value.") from error


def decode_response(payload: bytes) -> tuple[int, RequestResult, int, int, int, int]:
    """Decode one fixed 16-byte correlated operation response."""
    if len(payload) != _RESPONSE.size:
        raise ProtocolError("Parameter response must be 16 bytes.")
    opcode, raw_result, transaction_id, parameter_id, value, revision = (
        _RESPONSE.unpack(payload)
    )
    if opcode not in (_GET_PARAMETER, _SET_PARAMETER):
        raise ProtocolError("Parameter response has an invalid opcode.")
    try:
        result = RequestResult(raw_result)
    except ValueError as error:
        raise ProtocolError("Parameter response has an invalid result.") from error
    return opcode, result, transaction_id, parameter_id, value, revision
