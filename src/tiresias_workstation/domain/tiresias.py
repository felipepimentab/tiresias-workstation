"""Define platform-neutral Tiresias service models and client operations.

The module is the stable boundary consumed by application use cases. Wire
layouts, UUIDs, Bleak objects, and Qt types remain in outer layers.
"""

from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Protocol

from tiresias_workstation.domain.devices import DiscoveredDevice


class ProtocolCapability(IntFlag):
    """Advertised operations and MVP behavior supported by the device."""

    GET_PARAMETER = 1
    SET_PARAMETER = 2
    PERSISTENCE = 4
    DSP_APPLY_DEFERRED = 8


class ParameterAccess(IntFlag):
    """Access and application properties of a catalog parameter."""

    READABLE = 1
    WRITABLE = 2
    PERSISTENT = 4
    LIVE = 8


class ParameterEncoding(IntEnum):
    """Value encoding identifiers carried by the wire catalog."""

    Q5_23 = 1


class ParameterUnit(IntEnum):
    """Unit identifiers carried by the wire catalog."""

    LINEAR = 1


class DeviceState(IntEnum):
    """Firmware control-service lifecycle states."""

    DISABLED = 0
    ADVERTISING = 1
    LINKED = 2
    READY = 3
    ERROR = 4


class StatusFlag(IntFlag):
    """Device status flags published by the custom service."""

    PARAMETERS_LOADED = 1
    LAST_SET_PERSISTED = 2
    DSP_APPLY_DEFERRED = 4


class RequestResult(IntEnum):
    """Terminal result codes returned for parameter operations."""

    OK = 0
    BAD_REQUEST = 1
    NOT_FOUND = 2
    READ_ONLY = 3
    OUT_OF_RANGE = 4
    BUSY = 5
    PERSIST_FAILED = 6
    INTERNAL = 7


@dataclass(frozen=True, slots=True)
class DeviceInformation:
    """Standard Device Information Service values exposed by a board."""

    manufacturer: str | None
    model_number: str | None
    serial_number: str | None
    hardware_revision: str | None
    firmware_revision: str | None


@dataclass(frozen=True, slots=True)
class ProtocolInformation:
    """Compatibility and capacity metadata for the Tiresias service."""

    major: int
    minor: int
    capabilities: ProtocolCapability
    maximum_request_size: int
    maximum_response_size: int
    catalog_entry_size: int
    catalog_count: int
    layout_id: int
    catalog_crc32: int
    boot_id: int
    parameter_revision: int


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    """Coherent service-state snapshot reported by the firmware."""

    state: DeviceState
    flags: StatusFlag
    last_result: RequestResult
    parameter_revision: int
    last_transaction_id: int
    last_parameter_id: int


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """One safe, stable DSP parameter exposed by the firmware catalog."""

    parameter_id: int
    access: ParameterAccess
    encoding: ParameterEncoding
    dsp_address: int
    word_count: int
    unit: ParameterUnit
    minimum: int
    maximum: int
    default: int
    step: int
    name: str

    def accepts(self, value: int) -> bool:
        """Return whether ``value`` satisfies catalog bounds and step.

        Args:
            value: Encoded signed 32-bit parameter value.

        Returns:
            ``True`` when the value may be sent to the device.
        """
        return (
            self.minimum <= value <= self.maximum
            and self.step > 0
            and (value - self.minimum) % self.step == 0
        )


@dataclass(frozen=True, slots=True)
class DeviceSession:
    """Identity, compatibility, status, and catalog read after connection."""

    information: DeviceInformation
    protocol: ProtocolInformation
    status: DeviceStatus
    catalog: tuple[ParameterDefinition, ...]


@dataclass(frozen=True, slots=True)
class ParameterValue:
    """A correlated parameter read or persistent write result."""

    parameter_id: int
    value: int
    parameter_revision: int


class TiresiasClient(Protocol):
    """Describe complete board operations required by workstation use cases."""

    async def scan(self, on_device, *, timeout: float) -> list[DiscoveredDevice]:
        """Delegate a bounded BLE discovery scan."""

    async def connect(self, address: str, on_disconnected, *, timeout: float) -> None:
        """Connect to a device retained from the most recent scan."""

    async def disconnect(self) -> None:
        """Disconnect the active device, if any."""

    async def read_session(self) -> DeviceSession:
        """Read and validate identity, protocol, status, and full catalog."""

    async def read_parameter(self, parameter_id: int) -> ParameterValue:
        """Read one cataloged parameter by stable identifier."""

    async def write_parameter(self, parameter_id: int, value: int) -> ParameterValue:
        """Persist one cataloged parameter and return its committed revision."""


class ProtocolError(RuntimeError):
    """Report malformed, inconsistent, or incompatible service data."""


class RequestError(RuntimeError):
    """Report a correlated device-side parameter-operation rejection."""

    def __init__(self, result: RequestResult, parameter_id: int) -> None:
        """Create an actionable operation error.

        Args:
            result: Terminal firmware result code.
            parameter_id: Stable parameter identifier from the request.
        """
        self.result = result
        self.parameter_id = parameter_id
        message = result.name.replace("_", " ").lower()
        super().__init__(f"Parameter {parameter_id}: {message}.")
