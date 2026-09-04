"""Apply validated prescriptions through the platform-neutral board client."""

from collections.abc import Callable
from dataclasses import dataclass

from tiresias_workstation.domain.prescriptions import (
    PRESCRIPTION_FORMAT_NAME,
    PRESCRIPTION_FORMAT_VERSION,
    Prescription,
)
from tiresias_workstation.domain.tiresias import (
    DeviceSession,
    ProtocolCapability,
    TiresiasClient,
)


@dataclass(frozen=True, slots=True)
class PrescriptionLoadProgress:
    """Describe one firmware-confirmed step of a prescription transfer."""

    profile_id: str
    completed_parameters: int
    total_parameters: int
    completed_bytes: int
    total_bytes: int
    parameter_id: int
    parameter_revision: int


@dataclass(frozen=True, slots=True)
class PrescriptionLoadResult:
    """Summarize a complete prescription transfer confirmed by the board."""

    profile_id: str
    parameter_count: int
    payload_byte_count: int
    parameter_revision: int


class PrescriptionLoadError(RuntimeError):
    """Report preflight or transfer failure with partial-progress context."""

    def __init__(
        self,
        profile_id: str,
        message: str,
        *,
        completed_parameters: int,
        total_parameters: int,
        parameter_id: int | None = None,
    ) -> None:
        """Create an actionable prescription failure.

        Args:
            profile_id: Stable identifier of the prescription being loaded.
            message: Underlying validation, transport, or board error.
            completed_parameters: Parameters confirmed before the failure.
            total_parameters: Total parameter count in the prescription.
            parameter_id: Parameter active at failure, when applicable.
        """
        self.profile_id = profile_id
        self.completed_parameters = completed_parameters
        self.total_parameters = total_parameters
        self.parameter_id = parameter_id
        location = (
            f" at parameter {parameter_id}" if parameter_id is not None else ""
        )
        super().__init__(
            f"{profile_id} failed{location} after {completed_parameters}/"
            f"{total_parameters} parameters: {message}"
        )


ProgressCallback = Callable[[PrescriptionLoadProgress], None]


class PrescriptionLoader:
    """Validate and sequentially persist any supported prescription format."""

    async def load(
        self,
        client: TiresiasClient,
        session: DeviceSession,
        prescription: Prescription,
        on_progress: ProgressCallback | None = None,
    ) -> PrescriptionLoadResult:
        """Persist every prescription parameter after a complete preflight.

        The preflight finishes before the first board write, preventing known
        format or contract incompatibilities from creating a partial profile.
        Writes are then serialized in prescription order. A runtime failure can
        still leave already-confirmed parameters and part of the active
        multi-chunk parameter persisted. The raised error reports the confirmed
        count and directs the caller to retry the complete prescription.

        Args:
            client: Connected, validated Tiresias board client.
            session: Session snapshot used to preflight the device contract.
            prescription: Format-versioned parameter values to load.
            on_progress: Optional callback after each confirmed parameter.

        Returns:
            Firmware-confirmed transfer summary.

        Raises:
            PrescriptionLoadError: If preflight or a parameter write fails.
        """
        self._preflight(session, prescription)
        total_parameters = len(prescription.parameters)
        total_bytes = prescription.payload_byte_count
        completed_bytes = 0
        final_revision = session.protocol.parameter_revision

        for completed, parameter in enumerate(prescription.parameters, start=1):
            try:
                value = await client.write_parameter(
                    int(parameter.parameter_id), parameter.data
                )
                if (
                    value.parameter_id != int(parameter.parameter_id)
                    or value.data != parameter.data
                ):
                    raise RuntimeError(
                        "The board confirmation did not match the requested value."
                    )
            except Exception as error:
                raise PrescriptionLoadError(
                    prescription.profile_id,
                    (str(error).strip() or error.__class__.__name__)
                    + "; retry the complete prescription because the active "
                    "parameter may be partially persisted",
                    completed_parameters=completed - 1,
                    total_parameters=total_parameters,
                    parameter_id=int(parameter.parameter_id),
                ) from error

            completed_bytes += len(parameter.data)
            final_revision = value.parameter_revision
            if on_progress is not None:
                on_progress(
                    PrescriptionLoadProgress(
                        prescription.profile_id,
                        completed,
                        total_parameters,
                        completed_bytes,
                        total_bytes,
                        int(parameter.parameter_id),
                        final_revision,
                    )
                )

        return PrescriptionLoadResult(
            prescription.profile_id,
            total_parameters,
            total_bytes,
            final_revision,
        )

    @staticmethod
    def _preflight(session: DeviceSession, prescription: Prescription) -> None:
        """Reject unsupported formats and device contracts before writing."""
        total_parameters = len(prescription.parameters)
        if (
            prescription.format_name != PRESCRIPTION_FORMAT_NAME
            or prescription.format_version != PRESCRIPTION_FORMAT_VERSION
        ):
            raise PrescriptionLoadError(
                prescription.profile_id,
                f"unsupported format {prescription.format_name!r} "
                f"version {prescription.format_version}",
                completed_parameters=0,
                total_parameters=total_parameters,
            )

        required_capabilities = (
            ProtocolCapability.SET_PARAMETER
            | ProtocolCapability.PERSISTENCE
        )
        if (
            session.protocol.capabilities & required_capabilities
            != required_capabilities
        ):
            raise PrescriptionLoadError(
                prescription.profile_id,
                "the connected board cannot persist parameter values",
                completed_parameters=0,
                total_parameters=total_parameters,
            )

        definitions = {
            int(definition.parameter_id): definition
            for definition in session.parameters
        }
        for parameter in prescription.parameters:
            parameter_id = int(parameter.parameter_id)
            definition = definitions.get(parameter_id)
            if definition is None:
                raise PrescriptionLoadError(
                    prescription.profile_id,
                    "the connected board does not expose this parameter",
                    completed_parameters=0,
                    total_parameters=total_parameters,
                    parameter_id=parameter_id,
                )
            if len(parameter.data) != definition.byte_count:
                raise PrescriptionLoadError(
                    prescription.profile_id,
                    f"board requires {definition.byte_count} bytes, "
                    f"prescription contains {len(parameter.data)}",
                    completed_parameters=0,
                    total_parameters=total_parameters,
                    parameter_id=parameter_id,
                )
            if not definition.writable:
                raise PrescriptionLoadError(
                    prescription.profile_id,
                    "the connected board marks this parameter read-only",
                    completed_parameters=0,
                    total_parameters=total_parameters,
                    parameter_id=parameter_id,
                )
