"""Adapt pyClarity's CEC1 CAMFIT rule to workstation domain targets.

The adapter is the only module that imports pyClarity and NumPy.  Application
and domain code therefore remain independent of the fitting implementation and
can register another prescription rule alongside CAMFIT later.
"""

from __future__ import annotations

from typing import Any

from tiresias_workstation.domain.fittings import (
    Audiogram,
    PrescriptionRuleMetadata,
    PrescriptionTarget,
)


PYCLARITY_REVISION = "9df6486fb0bddc7619b3b99f1b3a5c72c109a3ec"
FILTERBANK_CENTRES_HZ = (
    177.0,
    297.0,
    500.0,
    841.0,
    1414.0,
    2378.0,
    4000.0,
    6727.0,
    11314.0,
)
FILTERBANK_EDGES_HZ = (
    0.0,
    229.2793,
    385.357,
    648.4597,
    1090.5,
    1833.7,
    3084.2,
    5187.3,
    8724.1,
    22050.0,
)
NOISE_GATE_LEVELS_DB_SPL = (38.0, 38.0, 36.0, 37.0, 32.0, 26.0, 23.0, 22.0, 8.0)
INPUT_LEVELS_DB_SPL = tuple(float(level) for level in range(-10, 111))


class PyClarityUnavailableError(RuntimeError):
    """Report that the CAMFIT runtime dependency is not installed correctly."""


class PyClarityCamfitRule:
    """Generate exact CEC1 CAMFIT gain tables through pyClarity."""

    @property
    def metadata(self) -> PrescriptionRuleMetadata:
        """Return the pinned rule identity exposed to application code."""
        return PrescriptionRuleMetadata(
            rule_id="camfit-compressive-cec1",
            display_name="CAMFIT compressive (CEC1)",
            version=PYCLARITY_REVISION,
            source="https://github.com/claritychallenge/clarity",
        )

    def generate(self, audiogram: Audiogram) -> PrescriptionTarget:
        """Generate a two-ear, nine-band CAMFIT target.

        Args:
            audiogram: User-entered hearing thresholds for both ears.

        Returns:
            Full gain-versus-input-level target, rounded to six decimals to
            match the evaluation artifacts, for both ears.

        Raises:
            PyClarityUnavailableError: If pyClarity or NumPy cannot be imported.
            RuntimeError: If pyClarity returns an incompatible or unsafe table.
        """
        np, clarity_audiogram, get_gaintable = self._load_backend()
        frequencies = np.asarray(audiogram.frequencies_hz, dtype=float)
        left = clarity_audiogram(
            levels=np.asarray(audiogram.left_levels_db_hl, dtype=float),
            frequencies=frequencies,
        )
        right = clarity_audiogram(
            levels=np.asarray(audiogram.right_levels_db_hl, dtype=float),
            frequencies=frequencies,
        )
        table = get_gaintable(
            audiogram_left=left,
            audiogram_right=right,
            noisegate_levels=np.asarray(NOISE_GATE_LEVELS_DB_SPL, dtype=float),
            noisegate_slope=0.0,
            cr_level=0.0,
            max_output_level=100.0,
        )
        corrected = np.asarray(table["sGt"], dtype=float).copy()
        if corrected.shape != (18, 121):
            raise RuntimeError(
                "pyClarity returned gain table shape "
                f"{corrected.shape}, expected (18, 121)."
            )
        corrected[[8, 17], :] = 0.0
        input_levels = np.asarray(INPUT_LEVELS_DB_SPL, dtype=float)
        for offset, thresholds in (
            (0, audiogram.left_levels_db_hl),
            (9, audiogram.right_levels_db_hl),
        ):
            # pyClarity explicitly bypasses all gain/limiting for a flat 0 dB
            # HL ear. Preserve that reference behavior, including above 100 SPL.
            if not any(thresholds):
                continue
            output = input_levels[None, :] + corrected[offset:offset + 8]
            if np.max(output) > 100.0 + 1e-6:
                raise RuntimeError(
                    "CAMFIT target exceeds the 100 dB SPL output ceiling."
                )
        if not np.all(
            np.diff(input_levels[None, :] + corrected, axis=1) >= -1e-6
        ):
            raise RuntimeError(
                "CAMFIT target contains a non-monotonic input/output map."
            )

        return PrescriptionTarget(
            rule=self.metadata,
            audiogram=audiogram,
            band_centres_hz=FILTERBANK_CENTRES_HZ,
            band_edges_hz=FILTERBANK_EDGES_HZ,
            input_levels_db_spl=INPUT_LEVELS_DB_SPL,
            left_gain_db_by_band=self._rounded_matrix(corrected[:9]),
            right_gain_db_by_band=self._rounded_matrix(corrected[9:]),
            attack_time_ms=20.0,
            release_time_ms=100.0,
            rms_level_time_constant_ms=100.0,
            endpoint_policy=(
                "pyClarity constant extension below the lowest and above the highest "
                "audiogram frequency"
            ),
        )

    @staticmethod
    def _load_backend() -> tuple[Any, Any, Any]:
        """Import the isolated external implementation at the call boundary."""
        try:
            import numpy as np
            from clarity.enhancer.gha.gha_utils import get_gaintable
            from clarity.utils.audiogram import Audiogram as ClarityAudiogram
        except ImportError as error:
            raise PyClarityUnavailableError(
                "CAMFIT generation requires the locked pyClarity runtime. "
                "Run `uv sync` in the workstation repository."
            ) from error
        return np, ClarityAudiogram, get_gaintable

    @staticmethod
    def _rounded_matrix(matrix: Any) -> tuple[tuple[float, ...], ...]:
        """Match the six-decimal evaluation artifact representation."""
        return tuple(
            tuple(round(float(value), 6) for value in row)
            for row in matrix
        )
