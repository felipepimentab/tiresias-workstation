"""Map fitting targets to calibrated ADAU1787 SigmaDSP parameter bytes.

This adapter reproduces the target-to-parameter stage from ``tiresias-eval``.
It samples each rule target on the measured detector transfer, fits the coarse
3 dB compressor grid at validation checkpoints, moves excess positive gain to
the three phase-compensation stages, and quantizes all gains as big-endian 5.23
words.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from tiresias_workstation.domain.dsp_contract import DspParameterId
from tiresias_workstation.domain.fittings import (
    DspMapping,
    Ear,
    PrescriptionTarget,
)
from tiresias_workstation.domain.prescriptions import (
    PRESCRIPTION_FORMAT_NAME,
    PRESCRIPTION_FORMAT_VERSION,
    Prescription,
    PrescriptionParameter,
    PrescriptionSource,
    prescription_sha256,
)


CALIBRATION_ID = "ADAU1787_EVAL_Tiresias_2026"
ACTIVE_BAND_CENTRES_HZ = (177.0, 297.0, 500.0, 841.0, 1414.0, 2378.0, 4000.0, 6727.0)
DETECTOR_POINTS_DBFS = (
    -90.0,
    -90.0,
    *tuple(float(value) for value in range(-87, 7, 3)),
)
VALIDATION_LEVELS_DB_SPL = (45.0, 55.0, 65.0, 75.0, 85.0, 95.0)
MAXIMUM_LUT_GAIN_DB = 21.0
BIAS_PARAMETER_IDS = (
    DspParameterId.PHASE_COMP_GAIN_1,
    DspParameterId.PHASE_COMP_GAIN_2,
    DspParameterId.PHASE_COMP_GAIN_3,
)
COMPRESSOR_PARAMETER_IDS = tuple(
    DspParameterId(value) for value in range(3, 11)
)


_EQUIVALENT_LEVELS = (45.0, 65.0, 85.0, 95.0)
_DETECTOR_CALIBRATIONS: tuple[dict[str, Any], ...] = (
    {"detector": (-40.162501, -35.139349, -17.13609, -7.175152), "low_floor": True},
    {"detector": (-59.565154, -39.632526, -19.897802, -9.792284), "low_floor": False},
    {"detector": (-59.895879, -40.076409, -20.197084, -10.253938), "low_floor": False},
    {"detector": (-59.91426, -40.153535, -20.267644, -10.261084), "low_floor": False},
    {"detector": (-59.890692, -40.153297, -20.204077, -10.334106), "low_floor": False},
    {"detector": (-59.785201, -40.152233, -20.181457, -10.159175), "low_floor": False},
    {"detector": (-59.792207, -40.0, -20.085683, -10.089514), "low_floor": False},
    {"detector": (-59.298983, -39.290631, -19.567023, -9.396888), "low_floor": False},
)


class SigmaDspMapper:
    """Convert either ear of a fitting target to the monaural board contract."""

    def map(
        self,
        target: PrescriptionTarget,
        *,
        artifact_id: str,
        name: str,
        ear: Ear,
    ) -> tuple[Prescription, DspMapping]:
        """Generate calibrated LUT and phase-compensation parameter values.

        Args:
            target: Exact rule output for both ears.
            artifact_id: Stable local identifier used as the board profile ID.
            name: User-facing custom prescription name.
            ear: Ear selected for the current monaural DSP path.

        Returns:
            Transport-ready prescription and inspectable conversion metadata.

        Raises:
            ValueError: If the target does not provide the eight active CAMFIT
                bands or cannot be represented by positive 5.23 gains.
        """
        gains = target.gains(ear)
        if target.band_centres_hz[:8] != ACTIVE_BAND_CENTRES_HZ:
            raise ValueError(
                "The Tiresias detector calibration requires its eight active band "
                "centres. Resample a different rule's filterbank before DSP mapping."
            )
        levels = target.input_levels_db_spl
        mapped_levels = tuple(
            tuple(
                self._equivalent_spl_from_detector(point, calibration)
                for point in DETECTOR_POINTS_DBFS
            )
            for calibration in _DETECTOR_CALIBRATIONS
        )
        desired = [
            [self._interpolate(level, levels, gain_curve) for level in band_levels]
            for band_levels, gain_curve in zip(mapped_levels, gains[:8])
        ]
        for band_index, calibration in enumerate(_DETECTOR_CALIBRATIONS):
            checkpoint_detector = [
                self._detector_from_equivalent_spl(level, calibration)
                for level in VALIDATION_LEVELS_DB_SPL
            ]
            checkpoint_target = [
                self._interpolate(level, levels, gains[band_index])
                for level in VALIDATION_LEVELS_DB_SPL
            ]
            desired[band_index] = self._fit_lut_to_checkpoints(
                checkpoint_detector,
                checkpoint_target,
                desired[band_index],
            )

        maximum_desired = max(max(row) for row in desired)
        bias_total_db = max(0.0, maximum_desired - MAXIMUM_LUT_GAIN_DB)
        bias_stage_db = bias_total_db / len(BIAS_PARAMETER_IDS)
        residual = [
            [value - bias_total_db for value in row]
            for row in desired
        ]

        parameters: list[PrescriptionParameter] = []
        quantized_rows: list[tuple[float, ...]] = []
        for parameter_id, row in zip(COMPRESSOR_PARAMETER_IDS, residual):
            encoded = [self._fixed_5_23_from_db(value) for value in row]
            parameters.append(
                PrescriptionParameter(
                    parameter_id,
                    b"".join(word for _, word in encoded),
                )
            )
            quantized_rows.append(
                tuple(
                    20.0 * math.log10(integer / float(1 << 23))
                    for integer, _word in encoded
                )
            )

        bias_integer, bias_word = self._fixed_5_23_from_db(bias_stage_db)
        for parameter_id in BIAS_PARAMETER_IDS:
            parameters.append(PrescriptionParameter(parameter_id, bias_word))
        parameter_tuple = tuple(parameters)
        target_digest = self._target_sha256(target)
        prescription = Prescription(
            profile_id=artifact_id,
            display_name=name,
            description=(
                f"{target.rule.display_name} target generated from a custom "
                f"audiogram; {ear} ear mapped to the monaural DSP path."
            ),
            format_name=PRESCRIPTION_FORMAT_NAME,
            format_version=PRESCRIPTION_FORMAT_VERSION,
            parameters=parameter_tuple,
            expected_sha256=prescription_sha256(parameter_tuple),
            source=PrescriptionSource(
                repository="tiresias-workstation",
                path=f"generated-prescriptions/{artifact_id}.json",
                revision=target.rule.version,
                sha256=target_digest,
            ),
        )
        mapping = DspMapping(
            calibration_id=CALIBRATION_ID,
            ear=ear,
            detector_points_dbfs=DETECTOR_POINTS_DBFS,
            mapped_input_levels_db_spl_by_band=mapped_levels,
            desired_gain_db_by_band=tuple(tuple(row) for row in desired),
            lut_gain_db_by_band=tuple(tuple(row) for row in residual),
            quantized_lut_gain_db_by_band=tuple(quantized_rows),
            common_bias_total_db=bias_total_db,
            quantized_bias_per_stage_db=(
                20.0 * math.log10(bias_integer / float(1 << 23))
            ),
        )
        return prescription, mapping

    @staticmethod
    def _interpolate(
        x: float,
        xp: tuple[float, ...],
        fp: tuple[float, ...],
    ) -> float:
        """Linearly interpolate with constant extension at both endpoints."""
        if x <= xp[0]:
            return fp[0]
        if x >= xp[-1]:
            return fp[-1]
        right = next(index for index, value in enumerate(xp) if value >= x)
        if xp[right] == x:
            return fp[right]
        left = right - 1
        fraction = (x - xp[left]) / (xp[right] - xp[left])
        return fp[left] + fraction * (fp[right] - fp[left])

    @staticmethod
    def _piecewise(
        x: float,
        xp: tuple[float, ...],
        fp: tuple[float, ...],
        *,
        hold_low: bool,
    ) -> float:
        """Interpolate calibration data and extrapolate its high endpoint."""
        def segment(left: int, right: int) -> float:
            fraction = (x - xp[left]) / (xp[right] - xp[left])
            return fp[left] + fraction * (fp[right] - fp[left])

        if x <= xp[0]:
            return fp[0] if hold_low else segment(0, 1)
        if x >= xp[-1]:
            return segment(-2, -1)
        right = next(index for index, value in enumerate(xp) if value >= x)
        return segment(right - 1, right)

    @classmethod
    def _equivalent_spl_from_detector(
        cls, detector_dbfs: float, calibration: dict[str, Any]
    ) -> float:
        """Map one detector knot to its measured equivalent acoustic level."""
        return cls._piecewise(
            detector_dbfs,
            tuple(calibration["detector"]),
            _EQUIVALENT_LEVELS,
            hold_low=bool(calibration["low_floor"]),
        )

    @classmethod
    def _detector_from_equivalent_spl(
        cls, equivalent_spl: float, calibration: dict[str, Any]
    ) -> float:
        """Invert the measured detector calibration at a fitting checkpoint."""
        return cls._piecewise(
            equivalent_spl,
            _EQUIVALENT_LEVELS,
            tuple(calibration["detector"]),
            hold_low=bool(calibration["low_floor"]),
        )

    @staticmethod
    def _fixed_5_23_from_db(gain_db: float) -> tuple[int, bytes]:
        """Quantize a dB gain as one positive big-endian 5.23 word."""
        linear = 10.0 ** (gain_db / 20.0)
        if not 0.0 < linear < 16.0:
            raise ValueError(f"Gain {gain_db:.6f} dB is outside positive 5.23 range.")
        integer = int(round(linear * (1 << 23)))
        if integer <= 0 or integer >= 0x08000000:
            raise ValueError(f"Gain {gain_db:.6f} dB cannot be encoded as 5.23.")
        return integer, integer.to_bytes(4, byteorder="big", signed=False)

    @classmethod
    def _fit_lut_to_checkpoints(
        cls,
        checkpoint_detectors: list[float],
        checkpoint_targets_db: list[float],
        initial_gain_db: list[float],
    ) -> list[float]:
        """Minimally adjust LUT knots to hit linear-gain checkpoints."""
        grid = list(DETECTOR_POINTS_DBFS[1:])
        base = [10.0 ** (value / 20.0) for value in initial_gain_db[1:]]
        rows: list[list[float]] = []
        targets: list[float] = []
        for detector, target_db in zip(
            checkpoint_detectors, checkpoint_targets_db
        ):
            row = [0.0] * len(grid)
            if detector <= grid[0]:
                row[0] = 1.0
            elif detector >= grid[-1]:
                row[-1] = 1.0
            else:
                right = next(
                    index for index, value in enumerate(grid) if value >= detector
                )
                if grid[right] == detector:
                    row[right] = 1.0
                else:
                    left = right - 1
                    fraction = (detector - grid[left]) / (grid[right] - grid[left])
                    row[left] = 1.0 - fraction
                    row[right] = fraction
            rows.append(row)
            targets.append(10.0 ** (target_db / 20.0))

        minimum_gain = 1e-4
        fixed: set[int] = set()
        while True:
            free = [index for index in range(len(base)) if index not in fixed]
            constrained = [
                target - sum(row[index] * minimum_gain for index in fixed)
                for row, target in zip(rows, targets)
            ]
            residual = [
                target - sum(row[index] * base[index] for index in free)
                for row, target in zip(rows, constrained)
            ]
            gram = [
                [
                    sum(row_a[index] * row_b[index] for index in free)
                    for row_b in rows
                ]
                for row_a in rows
            ]
            multipliers = cls._solve_linear_system(gram, residual)
            adjusted = [
                minimum_gain if index in fixed else base[index]
                for index in range(len(base))
            ]
            for index in free:
                adjusted[index] += sum(
                    rows[row_index][index] * multipliers[row_index]
                    for row_index in range(len(rows))
                )
            negative = [
                index for index in free if adjusted[index] < minimum_gain
            ]
            if not negative:
                break
            fixed.add(min(negative, key=lambda index: adjusted[index]))
        unique_db = [20.0 * math.log10(value) for value in adjusted]
        return [unique_db[0], *unique_db]

    @staticmethod
    def _solve_linear_system(
        matrix: list[list[float]], vector: list[float]
    ) -> list[float]:
        """Solve the small dense checkpoint system by pivoted elimination."""
        size = len(vector)
        augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
        for column in range(size):
            pivot = max(
                range(column, size),
                key=lambda row: abs(augmented[row][column]),
            )
            if abs(augmented[pivot][column]) < 1e-12:
                raise ValueError("Detector checkpoint fitting matrix is singular.")
            augmented[column], augmented[pivot] = (
                augmented[pivot],
                augmented[column],
            )
            scale = augmented[column][column]
            augmented[column] = [value / scale for value in augmented[column]]
            for row in range(size):
                if row == column:
                    continue
                factor = augmented[row][column]
                augmented[row] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(
                        augmented[row], augmented[column]
                    )
                ]
        return [augmented[row][-1] for row in range(size)]

    @staticmethod
    def _target_sha256(target: PrescriptionTarget) -> str:
        """Digest the deterministic rule input and output representation."""
        payload = {
            "rule": {
                "id": target.rule.rule_id,
                "version": target.rule.version,
            },
            "audiogram": {
                "frequencies_hz": target.audiogram.frequencies_hz,
                "left_levels_db_hl": target.audiogram.left_levels_db_hl,
                "right_levels_db_hl": target.audiogram.right_levels_db_hl,
            },
            "band_centres_hz": target.band_centres_hz,
            "band_edges_hz": target.band_edges_hz,
            "input_levels_db_spl": target.input_levels_db_spl,
            "left_gain_db_by_band": target.left_gain_db_by_band,
            "right_gain_db_by_band": target.right_gain_db_by_band,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
