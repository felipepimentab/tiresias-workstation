"""Adapt Clarity's NAL-R insertion gains to the workstation target contract.

Clarity uses these gains to design a broadband FIR filter. The workstation
instead samples the prescribed response at its fixed fitting-band centres;
the separate DSP mapper then compiles those constant gains for the board.
"""

from __future__ import annotations

import math

from tiresias_workstation.adapters.fitting_target_grid import (
    FILTERBANK_CENTRES_HZ,
    FILTERBANK_EDGES_HZ,
    INPUT_LEVELS_DB_SPL,
)
from tiresias_workstation.adapters.pyclarity_camfit import PYCLARITY_REVISION
from tiresias_workstation.domain.fittings import (
    Audiogram,
    PrescriptionRuleMetadata,
    PrescriptionTarget,
)


NALR_FREQUENCIES_HZ = (250.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0)
NALR_BIAS_DB = (-17.0, -8.0, 1.0, -1.0, -2.0, -2.0)


class PyClarityNalrRule:
    """Generate two-ear, level-independent NAL-R targets for the fixed bands."""

    @property
    def metadata(self) -> PrescriptionRuleMetadata:
        """Identify the Clarity formula and this band-target adaptation."""
        return PrescriptionRuleMetadata(
            rule_id="nal-r-clarity",
            display_name="NAL-R (fixed-band target)",
            version=f"{PYCLARITY_REVISION}:band-target-v1",
            source=(
                "https://github.com/claritychallenge/clarity/blob/"
                f"{PYCLARITY_REVISION}/clarity/enhancer/nalr.py"
            ),
        )

    def generate(self, audiogram: Audiogram) -> PrescriptionTarget:
        """Project Clarity's NAL-R gains onto the workstation fitting bands.

        Args:
            audiogram: Hearing thresholds for both ears in dB HL.

        Returns:
            Two-ear gain curves in dB, constant over the acoustic input grid.
            Frequency interpolation follows Clarity's linear FIR design axis.
        """
        return PrescriptionTarget(
            rule=self.metadata,
            audiogram=audiogram,
            band_centres_hz=FILTERBANK_CENTRES_HZ,
            band_edges_hz=FILTERBANK_EDGES_HZ,
            input_levels_db_spl=INPUT_LEVELS_DB_SPL,
            left_gain_db_by_band=self._band_gains(audiogram, "left"),
            right_gain_db_by_band=self._band_gains(audiogram, "right"),
            # These are the fixed DSP program settings, not NAL-R parameters.
            attack_time_ms=20.0,
            release_time_ms=100.0,
            rms_level_time_constant_ms=100.0,
            endpoint_policy=(
                "Clarity log-frequency audiogram resampling with constant endpoints; "
                "linear-frequency NAL-R gain interpolation with constant endpoints; "
                "fixed-band approximation of the Clarity FIR response"
            ),
        )

    @staticmethod
    def _interpolate(
        frequency_hz: float,
        frequencies_hz: tuple[float, ...],
        values: tuple[float, ...],
        *,
        logarithmic: bool,
    ) -> float:
        """Interpolate a frequency series with constant endpoint extension."""
        if frequency_hz <= frequencies_hz[0]:
            return values[0]
        if frequency_hz >= frequencies_hz[-1]:
            return values[-1]
        right = next(
            index for index, frequency in enumerate(frequencies_hz)
            if frequency >= frequency_hz
        )
        left = right - 1
        axis = math.log if logarithmic else float
        fraction = (
            (axis(frequency_hz) - axis(frequencies_hz[left]))
            / (axis(frequencies_hz[right]) - axis(frequencies_hz[left]))
        )
        return values[left] + fraction * (values[right] - values[left])

    @classmethod
    def _band_gains(
        cls, audiogram: Audiogram, ear: str
    ) -> tuple[tuple[float, ...], ...]:
        """Calculate Clarity's six insertion gains and sample the band centres."""
        thresholds = tuple(
            cls._interpolate(
                frequency, audiogram.frequencies_hz, audiogram.levels(ear),
                logarithmic=True,
            )
            for frequency in NALR_FREQUENCIES_HZ
        )
        if max(thresholds) <= 0.0:
            prescribed = (0.0,) * len(NALR_FREQUENCIES_HZ)
        else:
            critical_loss = sum(thresholds[1:4])
            average = (
                0.05 * critical_loss if critical_loss <= 180.0
                else 9.0 + 0.116 * (critical_loss - 180.0)
            )
            prescribed = tuple(
                max(0.0, average + 0.31 * threshold + bias)
                for threshold, bias in zip(thresholds, NALR_BIAS_DB)
            )
        return tuple(
            (round(cls._interpolate(
                centre, NALR_FREQUENCIES_HZ, prescribed,
                logarithmic=False,
            ), 6),) * len(INPUT_LEVELS_DB_SPL)
            for centre in FILTERBANK_CENTRES_HZ
        )
