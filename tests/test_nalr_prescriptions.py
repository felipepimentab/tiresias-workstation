"""Check Clarity NAL-R gain adaptation and the registered fitting workflow."""

import math
from pathlib import Path
import tempfile
import unittest

from clarity.utils.audiogram import Audiogram as ClarityAudiogram
import numpy as np

from tiresias_workstation.adapters.json_prescription_store import (
    artifact_from_dict,
    artifact_to_dict,
)
from tiresias_workstation.adapters.pyclarity_nalr import PyClarityNalrRule
from tiresias_workstation.application.default_prescriptions import (
    create_default_prescription_services,
)
from tiresias_workstation.domain.fittings import Audiogram


FREQUENCIES_HZ = (250.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0)


class NalrPrescriptionTests(unittest.TestCase):
    """Keep the formula, band projection, and persistence inspectable."""

    def test_clarity_reference_gains_and_level_independence(self):
        """Check the six formula points against hand-calculated NAL-R values."""
        thresholds = (45.0, 45.0, 35.0, 45.0, 60.0, 65.0)
        target = PyClarityNalrRule().generate(
            Audiogram(FREQUENCIES_HZ, thresholds, thresholds)
        )
        # Clarity's 500+1000+2000 Hz sum is 125 dB HL, so X_ave is 6.25 dB.
        self.assertEqual(target.gain_at("left", 2, 65.0), 12.2)
        self.assertEqual(target.gain_at("left", 6, 65.0), 22.85)
        self.assertEqual(target.gain_at("left", 2, -10.0), 12.2)
        self.assertEqual(target.gain_at("left", 2, 110.0), 12.2)
        self.assertEqual(target.gain_at("left", 0, 65.0), 3.2)
        self.assertEqual(target.gain_at("left", 7, 65.0), 24.4)
        self.assertEqual(len(target.band_centres_hz), 9)
        self.assertEqual(len(target.input_levels_db_spl), 121)

    def test_resampling_matches_clarity_and_high_loss_branch(self):
        """Preserve Clarity's log-frequency resampling and >180 dB branch."""
        frequencies = (250.0, 500.0, 1000.0, 1500.0, 4000.0, 6000.0)
        thresholds = (45.0, 45.0, 35.0, 45.0, 60.0, 65.0)
        audiogram = Audiogram(frequencies, thresholds, thresholds)
        target = PyClarityNalrRule().generate(audiogram)
        clarity_levels = ClarityAudiogram(
            np.asarray(thresholds), np.asarray(frequencies)
        ).resample(np.asarray(FREQUENCIES_HZ)).levels
        expected = max(0.0, 0.05 * sum(clarity_levels[1:4]) + 0.31 * clarity_levels[1] - 8)
        self.assertAlmostEqual(target.gain_at("left", 2, 65.0), expected, places=6)

        severe = (80.0,) * 6
        high = PyClarityNalrRule().generate(Audiogram(FREQUENCIES_HZ, severe, severe))
        average = 9.0 + 0.116 * (240.0 - 180.0)
        self.assertAlmostEqual(high.gain_at("left", 2, 65.0), average + 0.31 * 80 - 8)

    def test_zero_ear_and_independent_ears(self):
        """Clarity uses unity when resampled hearing loss has no positive point."""
        zero = (0.0,) * 6
        loss = (45.0, 45.0, 35.0, 45.0, 60.0, 65.0)
        target = PyClarityNalrRule().generate(Audiogram(FREQUENCIES_HZ, zero, loss))
        self.assertTrue(all(gain == 0.0 for row in target.gains("left") for gain in row))
        self.assertEqual(target.gain_at("right", 2, 65.0), 12.2)

    def test_default_workflow_generates_compiles_and_round_trips_nalr(self):
        """The two entry points share a rule and retain target provenance."""
        with tempfile.TemporaryDirectory() as directory:
            workbench, _ = create_default_prescription_services(Path(directory))
            self.assertEqual(
                tuple(rule.rule_id for rule in workbench.list_rules()),
                ("camfit-compressive-cec1", "nal-r-clarity"),
            )
            audiogram = Audiogram(
                FREQUENCIES_HZ,
                (0.0,) * 6,
                (45.0, 45.0, 35.0, 45.0, 60.0, 65.0),
            )
            artifact = workbench.generate(
                audiogram, rule_id="nal-r-clarity", name="NAL-R test", ear="right"
            )
            self.assertEqual(artifact.target.rule.rule_id, "nal-r-clarity")
            self.assertEqual(artifact.mapping.ear, "right")
            self.assertEqual(len(artifact.prescription.parameters), 11)
            self.assertTrue(math.isfinite(artifact.mapping.common_bias_total_db))
            self.assertEqual(artifact_from_dict(artifact_to_dict(artifact)), artifact)
            library = workbench.library
            self.assertIn("nal-r-clarity", library.rules)
            audio = library.save("audiograms", "Independent input", audiogram)
            library_target = library.generate_target(audio, "nal-r-clarity")
            self.assertEqual(library_target, artifact.target)
            target_entry = library.save(
                "targets", "Independent target", library_target,
                sources=(library.reference(audio),),
            )
            calibration = library.get("calibrations", "eval-detector")
            compiled = library.compile(
                target_entry, calibration, "right", "Independent compiled"
            )
            self.assertEqual(
                compiled.artifact.prescription.parameters,
                artifact.prescription.parameters,
            )


if __name__ == "__main__":
    unittest.main()
