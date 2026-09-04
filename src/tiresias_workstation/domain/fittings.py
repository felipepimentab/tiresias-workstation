"""Define audiograms, prescription targets, and DSP mapping artifacts.

These models preserve the boundaries between user-entered hearing thresholds,
rule-specific fitting targets, and the quantized values consumed by the fixed
Tiresias DSP contract.  They intentionally do not depend on Qt, pyClarity, or
JSON storage.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal, Protocol

from tiresias_workstation.domain.prescriptions import Prescription


Ear = Literal["left", "right"]


@dataclass(frozen=True, slots=True)
class Audiogram:
    """Describe air-conduction hearing thresholds for both ears.

    Attributes:
        frequencies_hz: Strictly increasing audiometric frequencies in Hz.
        left_levels_db_hl: Left-ear thresholds in dB HL.
        right_levels_db_hl: Right-ear thresholds in dB HL.
    """

    frequencies_hz: tuple[float, ...]
    left_levels_db_hl: tuple[float, ...]
    right_levels_db_hl: tuple[float, ...]

    def __post_init__(self) -> None:
        """Validate finite, aligned, ordered audiometric data."""
        point_count = len(self.frequencies_hz)
        if point_count < 2:
            raise ValueError("An audiogram requires at least two frequencies.")
        if (
            len(self.left_levels_db_hl) != point_count
            or len(self.right_levels_db_hl) != point_count
        ):
            raise ValueError("Audiogram frequencies and both ears must align.")
        if any(
            not math.isfinite(frequency) or frequency <= 0.0
            for frequency in self.frequencies_hz
        ):
            raise ValueError("Audiogram frequencies must be finite and positive.")
        if any(
            current <= previous
            for previous, current in zip(
                self.frequencies_hz, self.frequencies_hz[1:]
            )
        ):
            raise ValueError("Audiogram frequencies must be strictly increasing.")
        for levels in (self.left_levels_db_hl, self.right_levels_db_hl):
            if any(not math.isfinite(level) for level in levels):
                raise ValueError("Audiogram thresholds must be finite.")
            if any(level < -20.0 or level > 140.0 for level in levels):
                raise ValueError(
                    "Audiogram thresholds must be between -20 and 140 dB HL."
                )

    def levels(self, ear: Ear) -> tuple[float, ...]:
        """Return hearing thresholds for one ear.

        Args:
            ear: Ear whose thresholds should be returned.

        Returns:
            Thresholds in dB HL, aligned with :attr:`frequencies_hz`.
        """
        if ear not in ("left", "right"):
            raise ValueError("Audiogram ear must be left or right.")
        return self.left_levels_db_hl if ear == "left" else self.right_levels_db_hl


@dataclass(frozen=True, slots=True)
class PrescriptionRuleMetadata:
    """Identify a selectable prescription rule and implementation revision."""

    rule_id: str
    display_name: str
    version: str
    source: str


@dataclass(frozen=True, slots=True)
class PrescriptionTarget:
    """Preserve the full fitting target produced by a prescription rule.

    Gain matrices are indexed as ``[band][input-level]``.  The target keeps
    both ears even though the current Tiresias DSP signal path is monaural.

    Attributes:
        rule: Rule identity and implementation revision.
        audiogram: Exact input supplied to the rule.
        band_centres_hz: Fitting-band centre frequencies in Hz.
        band_edges_hz: Band edges in Hz; one more edge than centre.
        input_levels_db_spl: Input grid in dB SPL.
        left_gain_db_by_band: Left-ear gain curves in dB.
        right_gain_db_by_band: Right-ear gain curves in dB.
        attack_time_ms: Fixed compressor attack time in milliseconds.
        release_time_ms: Fixed compressor release time in milliseconds.
        rms_level_time_constant_ms: Fixed RMS detector time constant in
            milliseconds.
        endpoint_policy: Audiogram behavior outside its measured frequencies.
    """

    rule: PrescriptionRuleMetadata
    audiogram: Audiogram
    band_centres_hz: tuple[float, ...]
    band_edges_hz: tuple[float, ...]
    input_levels_db_spl: tuple[float, ...]
    left_gain_db_by_band: tuple[tuple[float, ...], ...]
    right_gain_db_by_band: tuple[tuple[float, ...], ...]
    attack_time_ms: float
    release_time_ms: float
    rms_level_time_constant_ms: float
    endpoint_policy: str

    def __post_init__(self) -> None:
        """Validate target axes and both gain matrices."""
        band_count = len(self.band_centres_hz)
        level_count = len(self.input_levels_db_spl)
        if band_count == 0 or level_count < 2:
            raise ValueError("A prescription target requires bands and input levels.")
        if len(self.band_edges_hz) != band_count + 1:
            raise ValueError("Band edges must contain one more value than centres.")
        for axis in (
            self.band_centres_hz,
            self.band_edges_hz,
            self.input_levels_db_spl,
        ):
            if any(not math.isfinite(value) for value in axis):
                raise ValueError("Prescription axes must be finite.")
            if any(current <= previous for previous, current in zip(axis, axis[1:])):
                raise ValueError("Prescription axes must be strictly increasing.")
        if self.band_edges_hz[0] < 0.0 or any(
            not lower < centre < upper
            for lower, centre, upper in zip(
                self.band_edges_hz, self.band_centres_hz, self.band_edges_hz[1:]
            )
        ):
            raise ValueError("Each positive band centre must lie between its edges.")
        if any(
            not math.isfinite(value) or value <= 0.0
            for value in (
                self.attack_time_ms,
                self.release_time_ms,
                self.rms_level_time_constant_ms,
            )
        ):
            raise ValueError("Prescription time constants must be finite and positive.")
        for matrix in (
            self.left_gain_db_by_band,
            self.right_gain_db_by_band,
        ):
            if len(matrix) != band_count:
                raise ValueError("Each gain matrix must define every fitting band.")
            if any(len(row) != level_count for row in matrix):
                raise ValueError("Each gain curve must align with the input grid.")
            if any(not math.isfinite(value) for row in matrix for value in row):
                raise ValueError("Prescription gains must be finite.")

    def gains(self, ear: Ear) -> tuple[tuple[float, ...], ...]:
        """Return the target gain matrix for one ear."""
        if ear not in ("left", "right"):
            raise ValueError("Prescription ear must be left or right.")
        return (
            self.left_gain_db_by_band
            if ear == "left"
            else self.right_gain_db_by_band
        )

    def gain_at(self, ear: Ear, band_index: int, input_level_db_spl: float) -> float:
        """Interpolate one band gain on the target input axis.

        Args:
            ear: Ear whose target should be inspected.
            band_index: Zero-based fitting-band index.
            input_level_db_spl: Acoustic input level in dB SPL.

        Returns:
            Gain in dB, with constant extension outside the target axis.

        Raises:
            IndexError: If ``band_index`` is outside the target matrix.
        """
        if not math.isfinite(input_level_db_spl):
            raise ValueError("Input level must be finite.")
        curve = self.gains(ear)[band_index]
        levels = self.input_levels_db_spl
        if input_level_db_spl <= levels[0]:
            return curve[0]
        if input_level_db_spl >= levels[-1]:
            return curve[-1]
        right = next(
            index
            for index, level in enumerate(levels)
            if level >= input_level_db_spl
        )
        if levels[right] == input_level_db_spl:
            return curve[right]
        left = right - 1
        fraction = (
            (input_level_db_spl - levels[left])
            / (levels[right] - levels[left])
        )
        return curve[left] + fraction * (curve[right] - curve[left])


class PrescriptionRule(Protocol):
    """Generate an inspectable fitting target from an audiogram."""

    @property
    def metadata(self) -> PrescriptionRuleMetadata:
        """Return stable rule metadata for selection and provenance."""
        ...

    def generate(self, audiogram: Audiogram) -> PrescriptionTarget:
        """Generate a fitting target for both ears."""
        ...


@dataclass(frozen=True, slots=True)
class DspMapping:
    """Record how a fitting target became quantized SigmaDSP values.

    Attributes:
        calibration_id: Detector calibration used for the conversion.
        ear: Target ear selected for the monaural DSP path.
        detector_points_dbfs: Fixed ADAU1787 LUT detector knots in dBFS.
        mapped_input_levels_db_spl_by_band: Acoustic level represented by each
            detector knot for each active band.
        desired_gain_db_by_band: Target gains sampled or fitted at each knot.
        lut_gain_db_by_band: Gains after subtracting the common bias.
        quantized_lut_gain_db_by_band: Gains recovered from encoded 5.23 words.
        common_bias_total_db: Shared gain moved into three phase-compensation
            stages so each LUT remains within the positive 5.23 range.
        quantized_bias_per_stage_db: Gain represented by each encoded bias word.
    """

    calibration_id: str
    ear: Ear
    detector_points_dbfs: tuple[float, ...]
    mapped_input_levels_db_spl_by_band: tuple[tuple[float, ...], ...]
    desired_gain_db_by_band: tuple[tuple[float, ...], ...]
    lut_gain_db_by_band: tuple[tuple[float, ...], ...]
    quantized_lut_gain_db_by_band: tuple[tuple[float, ...], ...]
    common_bias_total_db: float
    quantized_bias_per_stage_db: float

    def __post_init__(self) -> None:
        """Validate that every mapping matrix aligns with its detector axis."""
        if self.ear not in ("left", "right"):
            raise ValueError("DSP mapping ear must be left or right.")
        knot_count = len(self.detector_points_dbfs)
        if knot_count < 2:
            raise ValueError("DSP mapping requires at least two detector knots.")
        matrices = (
            self.mapped_input_levels_db_spl_by_band,
            self.desired_gain_db_by_band,
            self.lut_gain_db_by_band,
            self.quantized_lut_gain_db_by_band,
        )
        if any(len(matrix) != 8 for matrix in matrices):
            raise ValueError("The current DSP mapping requires eight active bands.")
        if any(len(row) != knot_count for matrix in matrices for row in matrix):
            raise ValueError("DSP mapping rows must align with detector knots.")
        numeric_values = (
            *self.detector_points_dbfs,
            *(value for matrix in matrices for row in matrix for value in row),
            self.common_bias_total_db,
            self.quantized_bias_per_stage_db,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise ValueError("DSP mapping values must be finite.")


@dataclass(frozen=True, slots=True)
class GeneratedPrescription:
    """Bundle every inspectable stage of one generated custom prescription."""

    artifact_id: str
    name: str
    created_at: str
    target: PrescriptionTarget
    mapping: DspMapping
    prescription: Prescription

    def __post_init__(self) -> None:
        """Keep artifact metadata aligned with transport-ready values."""
        if not self.artifact_id or not self.name:
            raise ValueError("Generated prescription identifiers and names are required.")
        if self.prescription.profile_id != self.artifact_id:
            raise ValueError("Artifact and DSP prescription identifiers must match.")
        if self.prescription.display_name != self.name:
            raise ValueError("Artifact and DSP prescription names must match.")


class DspPrescriptionMapper(Protocol):
    """Convert a rule target into the fixed board parameter contract."""

    def map(
        self,
        target: PrescriptionTarget,
        *,
        artifact_id: str,
        name: str,
        ear: Ear,
    ) -> tuple[Prescription, DspMapping]:
        """Create transport-ready parameters and conversion metadata."""
        ...


class GeneratedPrescriptionStore(Protocol):
    """Persist generated prescription artifacts independently of file layout."""

    def save(self, artifact: GeneratedPrescription) -> None:
        """Create or replace one artifact by stable identifier."""
        ...

    def list(self) -> tuple[GeneratedPrescription, ...]:
        """Return all saved artifacts in display order."""
        ...

    def get(self, artifact_id: str) -> GeneratedPrescription:
        """Return one saved artifact."""
        ...

    def delete(self, artifact_id: str) -> None:
        """Delete one saved artifact."""
        ...

    def export(self, artifact: GeneratedPrescription, path: Path) -> None:
        """Write a portable artifact without changing the local catalog."""
        ...
