"""Define the five independently stored fitting objects and their provenance.

Values are immutable and independent of UI, storage, fitting engines and BLE.
References bind an object ID to the exact source content used at generation.
"""

from dataclasses import dataclass
import math
import re
from typing import Literal

from tiresias_workstation.domain.fittings import Audiogram, GeneratedPrescription, PrescriptionTarget
from tiresias_workstation.domain.prescriptions import (
    PRESCRIPTION_FORMAT_NAME, PRESCRIPTION_FORMAT_VERSION, Prescription,
    PrescriptionParameter, PrescriptionSource, prescription_sha256,
)
from tiresias_workstation.domain.dsp_contract import DspParameterId

LibraryKind = Literal["audiograms", "targets", "calibrations", "compiled", "outputs"]
LIBRARY_KINDS = ("audiograms", "targets", "calibrations", "compiled", "outputs")


@dataclass(frozen=True, slots=True)
class CalibrationBand:
    """Pair RMS detector dBFS and equivalent input dB SPL at one test frequency."""

    frequency_hz: float
    detector_dbfs: tuple[float, ...]
    equivalent_input_db_spl: tuple[float, ...]
    hold_low: bool = False

    def __post_init__(self) -> None:
        """Reject nonfinite, unaligned or noninvertible calibration axes."""
        if not isinstance(self.hold_low, bool):
            raise ValueError("Calibration endpoint policy must be a boolean.")
        if not math.isfinite(self.frequency_hz) or self.frequency_hz <= 0:
            raise ValueError("Calibration frequency must be positive and finite.")
        if len(self.detector_dbfs) != len(self.equivalent_input_db_spl):
            raise ValueError("Detector and SPL checkpoints must align.")
        for axis in (self.detector_dbfs, self.equivalent_input_db_spl):
            if len(axis) < 2 or any(not math.isfinite(v) for v in axis):
                raise ValueError("Calibration needs at least two finite checkpoints.")
            if any(b <= a for a, b in zip(axis, axis[1:])):
                raise ValueError("Calibration checkpoints must be strictly increasing.")


@dataclass(frozen=True, slots=True)
class DeviceCalibration:
    """Describe independently measured B1–B8 detector transfer functions.

    High endpoints use linear extrapolation; low endpoints hold or extrapolate
    according to each band's policy. Scope and convention identify the measured
    device setup rather than claiming a universal microphone calibration.
    """

    calibration_id: str
    scope: str
    detector_convention: str
    bands: tuple[CalibrationBand, ...]
    provenance: str

    def __post_init__(self) -> None:
        """Require eight ordered bands and measurement context."""
        if len(self.bands) != 8:
            raise ValueError("Detector calibration requires all eight bands.")
        if any(b.frequency_hz <= a.frequency_hz for a, b in zip(self.bands, self.bands[1:])):
            raise ValueError("Calibration band frequencies must increase.")
        if not all(isinstance(v, str) and v.strip() for v in (self.calibration_id, self.scope, self.detector_convention)):
            raise ValueError("Calibration identity, scope and detector convention are required.")


@dataclass(frozen=True, slots=True)
class CompiledDspPrescription:
    """Retain executable bytes and immutable target/calibration/compiler evidence."""

    artifact: GeneratedPrescription
    calibration: DeviceCalibration
    compiler_version: str
    contract_crc32: int

    def __post_init__(self) -> None:
        """Keep compiled payloads and their calibration identity consistent."""
        if tuple(int(p.parameter_id) for p in self.artifact.prescription.parameters) != tuple(range(3, 14)):
            raise ValueError("Compiled prescriptions require exactly LUTs 3–10 and biases 11–13.")
        if self.artifact.mapping.calibration_id != self.calibration.calibration_id:
            raise ValueError("Compiled mapping and calibration identities differ.")
        if not self.compiler_version or not 0 <= self.contract_crc32 <= 0xFFFFFFFF:
            raise ValueError("Compiler version and contract fingerprint are required.")


@dataclass(frozen=True, slots=True)
class OutputStageConfiguration:
    """Describe output scaling and a nominal peak SoftClip transfer.

    Gains are dB; threshold and ceiling are dBFS peak. The 45-word table uses
    an underflow word then -90..39 dBFS in 3 dB steps. Hold and decay remain
    fixed DSP-program prerequisites because the current contract exposes only
    Headroom and SoftClip LUT values.
    """

    headroom_db: float
    threshold_dbfs_peak: float
    compression_ratio: float
    ceiling_dbfs_peak: float
    provenance: str
    hold_word_hex: str = "00000000"
    decay_word_hex: str = "0000013d"

    def __post_init__(self) -> None:
        """Validate a representable nominal transfer and fixed program timing."""
        if any(not math.isfinite(v) for v in (
            self.headroom_db, self.threshold_dbfs_peak,
            self.compression_ratio, self.ceiling_dbfs_peak,
        )):
            raise ValueError("Output-stage values must be finite.")
        if self.compression_ratio < 1 or self.compression_ratio > 100:
            raise ValueError("Compression ratio must be between 1 and 100.")
        if not -90 <= self.threshold_dbfs_peak < self.ceiling_dbfs_peak <= 0:
            raise ValueError("Require -90 ≤ threshold < ceiling ≤ 0 dBFS peak.")
        if self.hold_word_hex.lower() != "00000000" or self.decay_word_hex.lower() != "0000013d":
            raise ValueError("This DSP contract requires the exported fixed SoftClip hold/decay.")
        self.parameters()

    def parameters(self) -> tuple[PrescriptionParameter, ...]:
        """Encode headroom and the complete nominal SoftClip curve."""
        def word(db: float) -> bytes:
            value = round(10 ** (db / 20) * (1 << 23))
            if not 0 < value < 0x08000000:
                raise ValueError("Output gain cannot be represented in positive 5.23.")
            return value.to_bytes(4, "big")

        points = (-90, *range(-90, 40, 3))
        curve = []
        for point in points:
            output = point if point <= self.threshold_dbfs_peak else min(
                self.ceiling_dbfs_peak,
                self.threshold_dbfs_peak + (point - self.threshold_dbfs_peak) / self.compression_ratio,
            )
            curve.append(word(output - point))
        return (
            PrescriptionParameter(DspParameterId.OUTPUT_HEADROOM_GAIN, word(self.headroom_db)),
            PrescriptionParameter(DspParameterId.SOFT_CLIP_LUT, b"".join(curve)),
        )

    def prescription(self, item_id: str, name: str) -> Prescription:
        """Build a two-parameter board load using the existing transfer pipeline."""
        parameters = self.parameters()
        return Prescription(
            item_id, name, "Output headroom and nominal SoftClip configuration",
            PRESCRIPTION_FORMAT_NAME, PRESCRIPTION_FORMAT_VERSION, parameters,
            prescription_sha256(parameters),
            PrescriptionSource("tiresias-workstation", f"outputs/{item_id}", "1", prescription_sha256(parameters)),
        )


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Bind provenance to a stable library ID and a content SHA-256."""

    kind: LibraryKind
    item_id: str
    sha256: str

    def __post_init__(self) -> None:
        """Reject invalid source identities and malformed content fingerprints."""
        if self.kind not in LIBRARY_KINDS or not self.item_id or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Invalid source reference.")


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    """Give one independently reusable object a stable identity and provenance."""

    item_id: str
    name: str
    kind: LibraryKind
    value: Audiogram | PrescriptionTarget | DeviceCalibration | CompiledDspPrescription | OutputStageConfiguration
    sources: tuple[SourceReference, ...] = ()
    read_only: bool = False
    revision: int = 1
    provenance: str = "User-created"

    def __post_init__(self) -> None:
        """Require meaningful names and kind-specific value types."""
        types = dict(zip(LIBRARY_KINDS, (Audiogram, PrescriptionTarget, DeviceCalibration, CompiledDspPrescription, OutputStageConfiguration)))
        if self.kind not in types or not isinstance(self.value, types[self.kind]):
            raise ValueError("Library kind does not match its value.")
        if not isinstance(self.item_id, str) or not self.item_id or not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError("An identifier and a name of 1–100 characters are required.")
        expected = {"targets": ("audiograms",), "compiled": ("targets", "calibrations")}.get(self.kind, ())
        if tuple(source.kind for source in self.sources) != expected:
            raise ValueError(f"{self.kind} requires source references {expected}.")
        if self.kind == "compiled" and (self.value.artifact.artifact_id != self.item_id or self.value.artifact.name != self.name):
            raise ValueError("Compiled artifact identity must match its library entry.")
        if self.revision < 1:
            raise ValueError("Library revision must be positive.")
