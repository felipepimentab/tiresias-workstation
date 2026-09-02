"""Verify CAMFIT generation, calibrated DSP mapping, and JSON persistence."""

import copy
from dataclasses import replace
import json
import tempfile
from pathlib import Path
import unittest

from tiresias_workstation.adapters.bundled_prescriptions import (
    BUNDLED_PRESCRIPTION_CATALOG,
    N1_PRESCRIPTION,
)
from tiresias_workstation.adapters.json_prescription_store import (
    JsonPrescriptionStore,
    artifact_from_dict,
    artifact_to_dict,
)
from tiresias_workstation.adapters.pyclarity_camfit import PyClarityCamfitRule
from tiresias_workstation.adapters.prescription_catalogs import (
    CompositePrescriptionCatalog,
    SavedPrescriptionCatalog,
)
from tiresias_workstation.adapters.sigma_dsp_mapper import SigmaDspMapper
from tiresias_workstation.application.prescription_workbench import (
    PrescriptionWorkbench,
)
from tiresias_workstation.domain.fittings import (
    Audiogram,
    PrescriptionRuleMetadata,
    PrescriptionTarget,
)


N1_FREQUENCIES_HZ = (
    250.0,
    375.0,
    500.0,
    750.0,
    1000.0,
    1500.0,
    2000.0,
    3000.0,
    4000.0,
    6000.0,
)
N1_LEVELS_DB_HL = (
    10.0,
    10.0,
    10.0,
    10.0,
    10.0,
    10.0,
    15.0,
    20.0,
    30.0,
    40.0,
)

# Bisgaard 2010 inputs from tiresias-eval's bisgaard_2010_audiograms.csv.
REFERENCE_LEVELS_DB_HL = {
    "N1": N1_LEVELS_DB_HL,
    "N2": (20, 20, 20, 22.5, 25, 30, 35, 40, 45, 50),
    "N3": (35, 35, 35, 35, 40, 45, 50, 55, 60, 65),
    "N4": (55, 55, 55, 55, 55, 60, 65, 70, 75, 80),
    "N5": (65, 67.5, 70, 72.5, 75, 80, 80, 80, 80, 80),
    "N6": (75, 77.5, 80, 82.5, 85, 90, 90, 95, 100, 100),
    "N7": (90, 92.5, 95, 100, 105, 105, 105, 105, 105, 105),
    "S1": (10, 10, 10, 10, 10, 10, 15, 30, 55, 70),
    "S2": (20, 20, 20, 22.5, 25, 35, 55, 75, 95, 95),
    "S3": (30, 30, 35, 47.5, 60, 70, 75, 80, 80, 85),
}


class GeneratedPrescriptionTests(unittest.TestCase):
    """Keep every custom-prescription stage reproducible and portable."""

    @classmethod
    def setUpClass(cls):
        """Generate the pinned N1 reference once for all integration checks."""
        cls.audiogram = Audiogram(
            N1_FREQUENCIES_HZ,
            N1_LEVELS_DB_HL,
            N1_LEVELS_DB_HL,
        )
        cls.target = PyClarityCamfitRule().generate(cls.audiogram)

    def test_pyclarity_target_maps_to_the_validated_n1_parameter_bytes(self):
        """Match the evaluation pipeline from audiogram through quantization."""
        prescription, mapping = SigmaDspMapper().map(
            self.target,
            artifact_id="custom-reference-n1",
            name="Generated N1",
            ear="left",
        )

        self.assertEqual(len(self.target.band_centres_hz), 9)
        self.assertEqual(len(self.target.input_levels_db_spl), 121)
        self.assertEqual(prescription.sha256, N1_PRESCRIPTION.sha256)
        self.assertEqual(
            tuple(parameter.data for parameter in prescription.parameters),
            tuple(parameter.data for parameter in N1_PRESCRIPTION.parameters),
        )
        self.assertEqual(mapping.calibration_id, "ADAU1787_EVAL_Tiresias_2026")
        self.assertEqual(len(mapping.detector_points_dbfs), 34)

    def test_all_ten_standard_audiograms_match_bundled_parameter_bytes(self):
        """Cover mild, steep, severe, and profound evaluation references."""
        for profile_id, levels in REFERENCE_LEVELS_DB_HL.items():
            with self.subTest(profile_id=profile_id):
                target = PyClarityCamfitRule().generate(
                    Audiogram(N1_FREQUENCIES_HZ, levels, levels)
                )
                prescription, _ = SigmaDspMapper().map(
                    target, artifact_id="reference", name="Reference", ear="left"
                )
                reference = BUNDLED_PRESCRIPTION_CATALOG.get(profile_id)
                self.assertEqual(prescription.parameters, reference.parameters)
                self.assertEqual(prescription.sha256, reference.sha256)

    def test_flat_zero_and_asymmetric_audiograms_preserve_both_ears(self):
        """Keep pyClarity's unity special case without losing the other ear."""
        zero_levels = (0.0,) * len(N1_FREQUENCIES_HZ)
        rule = PyClarityCamfitRule()
        zero = rule.generate(Audiogram(N1_FREQUENCIES_HZ, zero_levels, zero_levels))
        self.assertTrue(all(value == 0 for row in zero.gains("left") for value in row))
        asymmetric = rule.generate(
            Audiogram(N1_FREQUENCIES_HZ, zero_levels, N1_LEVELS_DB_HL)
        )
        self.assertEqual(asymmetric.gains("left"), zero.gains("left"))
        self.assertEqual(asymmetric.gains("right"), self.target.gains("right"))
        prescription, _ = SigmaDspMapper().map(
            asymmetric, artifact_id="reference", name="Reference", ear="right"
        )
        self.assertEqual(prescription.parameters, N1_PRESCRIPTION.parameters)
        unity, _ = SigmaDspMapper().map(
            asymmetric, artifact_id="unity", name="Unity", ear="left"
        )
        for parameter in unity.parameters:
            self.assertEqual(parameter.data, bytes.fromhex("00800000") * (
                len(parameter.data) // 4
            ))

    def test_mapper_rejects_an_incompatible_filterbank(self):
        """Never silently apply the calibrated bands to another topology."""
        target = replace(
            self.target,
            band_centres_hz=(178.0, *self.target.band_centres_hz[1:]),
        )
        with self.assertRaisesRegex(ValueError, "band centres"):
            SigmaDspMapper().map(
                target, artifact_id="test", name="Test", ear="left"
            )

    def test_target_rejects_nonfinite_axes_and_time_constants(self):
        """Reject malformed stage data before interpolation or persistence."""
        with self.assertRaisesRegex(ValueError, "axes must be finite"):
            replace(self.target, input_levels_db_spl=(float("nan"), 100.0))
        with self.assertRaisesRegex(ValueError, "time constants"):
            replace(self.target, attack_time_ms=float("nan"))

    def test_rule_can_generate_target_without_hardware_mapping(self):
        """Allow independent target inspection with a separately injected rule."""
        with tempfile.TemporaryDirectory() as directory:
            workbench = PrescriptionWorkbench(
                (PyClarityCamfitRule(), ZeroGainRule()),
                SigmaDspMapper(),
                JsonPrescriptionStore(Path(directory)),
            )
            target = workbench.generate_target(self.audiogram, rule_id="zero")
            self.assertEqual(target.rule.rule_id, "zero")
            self.assertEqual(len(workbench.list_rules()), 2)
            self.assertEqual(workbench.list_saved(), ())
            with self.assertRaises(KeyError):
                workbench.generate_target(self.audiogram, rule_id="unknown")

    def test_store_round_trips_all_stages_and_supports_list_and_delete(self):
        """Persist the audiogram, target, mapping, and DSP values together."""
        with tempfile.TemporaryDirectory() as directory:
            store = JsonPrescriptionStore(Path(directory))
            workbench = PrescriptionWorkbench(
                (PyClarityCamfitRule(),),
                SigmaDspMapper(),
                store,
            )
            artifact = workbench.generate(
                self.audiogram,
                rule_id="camfit-compressive-cec1",
                name="My N1",
                ear="right",
            )

            workbench.save(artifact)
            restored = workbench.get_saved(artifact.artifact_id)

            self.assertEqual(restored, artifact)
            self.assertEqual(workbench.list_saved(), (artifact,))
            self.assertTrue(
                (Path(directory) / f"{artifact.artifact_id}.json").is_file()
            )
            catalog = CompositePrescriptionCatalog(
                BUNDLED_PRESCRIPTION_CATALOG,
                SavedPrescriptionCatalog(store),
            )
            self.assertEqual(len(catalog.list_prescriptions()), 11)
            self.assertEqual(catalog.get(artifact.artifact_id), artifact.prescription)
            export_path = Path(directory) / "portable-copy.json"
            workbench.export(artifact, export_path)
            exported = artifact_from_dict(json.loads(export_path.read_text()))
            self.assertEqual(exported, artifact)
            export_path.unlink()
            workbench.delete(artifact.artifact_id)
            self.assertEqual(workbench.list_saved(), ())

    def test_store_rejects_path_traversal(self):
        """Keep get and delete operations inside the local artifact directory."""
        with tempfile.TemporaryDirectory() as directory:
            store = JsonPrescriptionStore(Path(directory))
            for artifact_id in ("../outside", "/tmp/outside", "nested/name"):
                with self.subTest(artifact_id=artifact_id):
                    with self.assertRaises(ValueError):
                        store.get(artifact_id)
                    with self.assertRaises(ValueError):
                        store.delete(artifact_id)

    def test_import_rejects_parameter_bytes_that_do_not_match_the_digest(self):
        """Detect corruption in exported opaque DSP parameter values."""
        with tempfile.TemporaryDirectory() as directory:
            workbench = PrescriptionWorkbench(
                (PyClarityCamfitRule(),),
                SigmaDspMapper(),
                JsonPrescriptionStore(Path(directory)),
            )
            artifact = workbench.generate(
                self.audiogram,
                rule_id="camfit-compressive-cec1",
                name="Integrity test",
                ear="left",
            )
        value = copy.deepcopy(artifact_to_dict(artifact))
        first = value["dsp_parameters"]["parameters"][0]
        first["data_hex"] = "ff" + first["data_hex"][2:]

        with self.assertRaisesRegex(ValueError, "failed integrity check"):
            artifact_from_dict(value)

    def test_store_ignores_one_damaged_file_when_listing_valid_artifacts(self):
        """Keep one local file from making the complete catalog unavailable."""
        with tempfile.TemporaryDirectory() as directory:
            store = JsonPrescriptionStore(Path(directory))
            (Path(directory) / "damaged.json").write_text(
                "not json", encoding="utf-8"
            )

            with self.assertLogs(
                "tiresias_workstation.adapters.json_prescription_store",
                level="WARNING",
            ):
                self.assertEqual(store.list(), ())

    def test_audiogram_rejects_unordered_or_misaligned_thresholds(self):
        """Stop invalid fitting inputs before a rule implementation is called."""
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            Audiogram((500.0, 250.0), (10.0, 10.0), (10.0, 10.0))
        with self.assertRaisesRegex(ValueError, "must align"):
            Audiogram((250.0, 500.0), (10.0,), (10.0, 10.0))


class ZeroGainRule:
    """Provide a deterministic alternate rule for UI and registry tests."""

    @property
    def metadata(self) -> PrescriptionRuleMetadata:
        """Return a stable fake rule identity."""
        return PrescriptionRuleMetadata("zero", "Zero gain", "1", "tests")

    def generate(self, audiogram: Audiogram) -> PrescriptionTarget:
        """Return nine unity bands on the CAMFIT input grid."""
        levels = tuple(float(value) for value in range(-10, 111))
        row = (0.0,) * len(levels)
        return PrescriptionTarget(
            rule=self.metadata,
            audiogram=audiogram,
            band_centres_hz=(
                177.0,
                297.0,
                500.0,
                841.0,
                1414.0,
                2378.0,
                4000.0,
                6727.0,
                11314.0,
            ),
            band_edges_hz=(
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
            ),
            input_levels_db_spl=levels,
            left_gain_db_by_band=(row,) * 9,
            right_gain_db_by_band=(row,) * 9,
            attack_time_ms=20.0,
            release_time_ms=100.0,
            rms_level_time_constant_ms=100.0,
            endpoint_policy="constant",
        )


if __name__ == "__main__":
    unittest.main()
