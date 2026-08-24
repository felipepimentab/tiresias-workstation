"""Define platform-neutral Tiresias service models and client operations.

The module is the stable boundary consumed by application use cases. Wire
layouts, UUIDs, Bleak objects, and Qt types remain in outer layers.
"""

from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Protocol

from tiresias_workstation.domain.devices import DiscoveredDevice
from tiresias_workstation.domain.dsp_contract import DspParameterDefinition


class ProtocolCapability(IntFlag):
    """Advertised operations and MVP behavior supported by the device."""

    GET_PARAMETER = 1
    SET_PARAMETER = 2
    PERSISTENCE = 4
    DSP_APPLY_DEFERRED = 8


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
    DSP_FAILED = 8


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
    """Compatibility and fixed-contract metadata reported by the device."""

    major: int
    minor: int
    capabilities: ProtocolCapability
    maximum_request_size: int
    maximum_response_size: int
    contract_version: int
    parameter_count: int
    contract_id: int
    contract_crc32: int
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
    last_word_index: int


@dataclass(frozen=True, slots=True)
class DeviceSession:
    """Identity, compatibility, status, and fixed parameter definitions."""

    information: DeviceInformation
    protocol: ProtocolInformation
    status: DeviceStatus
    parameters: tuple[DspParameterDefinition, ...]


@dataclass(frozen=True, slots=True)
class ParameterValue:
    """A correlated complete parameter read or scalar write result."""

    parameter_id: int
    words: tuple[int, ...]
    parameter_revision: int

    @property
    def value(self) -> int:
        """Return the only word of a scalar parameter.

        Raises:
            ValueError: If this value contains more than one DSP word.
        """
        if len(self.words) != 1:
            raise ValueError("A multi-word parameter has no scalar value.")
        return self.words[0]


class TiresiasClient(Protocol):
    """Describe complete board operations required by workstation use cases."""

    async def scan(self, on_device, *, timeout: float) -> list[DiscoveredDevice]:
        """Delegate a bounded BLE discovery scan."""

    async def connect(self, address: str, on_disconnected, *, timeout: float) -> None:
        """Connect to a device retained from the most recent scan."""

    async def disconnect(self) -> None:
        """Disconnect the active device, if any."""

    async def read_session(self) -> DeviceSession:
        """Read identity, protocol, and status for the fixed contract."""

    async def read_parameter(self, parameter_id: int) -> ParameterValue:
        """Read every word of one parameter by stable identifier."""

    async def write_parameter(self, parameter_id: int, value: int) -> ParameterValue:
        """Persist one writable scalar parameter and return its revision."""


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
