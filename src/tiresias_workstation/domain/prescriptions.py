"""Define portable prescription metadata and opaque DSP parameter values.

The models in this module describe precomputed fittings without depending on a
storage format, transport, UI toolkit, or prescription engine.
"""

from dataclasses import dataclass
import hashlib
from typing import Protocol

from tiresias_workstation.domain.dsp_contract import (
    DSP_PARAMETERS_BY_ID,
    DspParameterId,
)


PRESCRIPTION_FORMAT_NAME = "SigmaDSP 5.23 big-endian parameter words"
PRESCRIPTION_FORMAT_VERSION = 1


def prescription_sha256(
    parameters: tuple["PrescriptionParameter", ...],
) -> str:
    """Return the canonical parameter identifier-and-value digest.

    Args:
        parameters: Ordered DSP parameter values.

    Returns:
        SHA-256 digest binding identifiers, payload sizes, and payload bytes.
    """
    digest = hashlib.sha256()
    for parameter in parameters:
        digest.update(bytes((int(parameter.parameter_id),)))
        digest.update(len(parameter.data).to_bytes(2, byteorder="big"))
        digest.update(parameter.data)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PrescriptionParameter:
    """Associate one stable DSP parameter identifier with its opaque bytes."""

    parameter_id: DspParameterId
    data: bytes


@dataclass(frozen=True, slots=True)
class PrescriptionSource:
    """Identify the versioned artifact from which a prescription was imported."""

    repository: str
    path: str
    revision: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Prescription:
    """Describe transport-ready DSP values for a bundled or custom fitting.

    The integrity digest covers each parameter identifier, its two-byte
    big-endian payload length, and its payload bytes in tuple order. This binds
    the opaque bytes to their stable DSP contract identifiers.

    Attributes:
        profile_id: Stable catalog identifier such as ``N1``.
        display_name: Human-readable catalog label.
        description: Short explanation of the fitting and target audiogram.
        format_name: Name of the opaque DSP parameter representation.
        format_version: Version of that representation.
        parameters: Complete parameter values in application order.
        expected_sha256: Expected digest of the canonical parameter encoding.
        source: Versioned provenance of the imported values.
    """

    profile_id: str
    display_name: str
    description: str
    format_name: str
    format_version: int
    parameters: tuple[PrescriptionParameter, ...]
    expected_sha256: str
    source: PrescriptionSource

    def __post_init__(self) -> None:
        """Validate identifiers, contract sizes, and bundled data integrity."""
        if not self.parameters:
            raise ValueError("A prescription must contain at least one parameter.")
        seen_ids: set[DspParameterId] = set()
        for parameter in self.parameters:
            if parameter.parameter_id in seen_ids:
                raise ValueError(
                    f"Duplicate prescription parameter {parameter.parameter_id}."
                )
            seen_ids.add(parameter.parameter_id)

            definition = DSP_PARAMETERS_BY_ID.get(parameter.parameter_id)
            if definition is None:
                raise ValueError(
                    f"Unknown prescription parameter {parameter.parameter_id}."
                )
            if not isinstance(parameter.data, bytes):
                raise TypeError("Prescription parameter data must be bytes.")
            if len(parameter.data) != definition.byte_count:
                raise ValueError(
                    f"Parameter {int(parameter.parameter_id)} requires "
                    f"{definition.byte_count} bytes, got {len(parameter.data)}."
                )

        if self.sha256 != self.expected_sha256:
            raise ValueError(f"Prescription {self.profile_id} failed integrity check.")

    @property
    def payload_byte_count(self) -> int:
        """Return the number of opaque DSP parameter bytes in the prescription."""
        return sum(len(parameter.data) for parameter in self.parameters)

    @property
    def sha256(self) -> str:
        """Return the canonical parameter identifier-and-value digest."""
        return prescription_sha256(self.parameters)

    def parameter(self, parameter_id: DspParameterId) -> PrescriptionParameter:
        """Return one parameter value by its stable DSP identifier.

        Args:
            parameter_id: Stable identifier from the workstation DSP contract.

        Returns:
            The matching opaque prescription parameter.

        Raises:
            KeyError: If the prescription does not define the parameter.
        """
        for parameter in self.parameters:
            if parameter.parameter_id == parameter_id:
                return parameter
        raise KeyError(parameter_id)


class PrescriptionCatalog(Protocol):
    """Provide prescriptions independently of their storage or origin."""

    def list_prescriptions(self) -> tuple[Prescription, ...]:
        """Return every available prescription in display order."""
        ...

    def get(self, profile_id: str) -> Prescription:
        """Return one prescription by stable profile identifier."""
        ...
