"""Exercise independent library CRUD, provenance and reference protection offline."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from tiresias_workstation.adapters.library_store import LibraryStore, content_sha256, entry_to_dict, entry_from_dict
from tiresias_workstation.adapters.pyclarity_camfit import PyClarityCamfitRule
from tiresias_workstation.adapters.bundled_prescriptions import N1_PRESCRIPTION
from tiresias_workstation.application.fitting_library import FittingLibrary
from tiresias_workstation.application.prescription_loader import PrescriptionLoader, PrescriptionLoadError
from tiresias_workstation.domain.library import CalibrationBand
from test_ble_controller import device_session
from test_prescription_loader import FakePrescriptionClient
from test_generated_prescriptions import ZeroGainRule


class FittingLibraryTest(unittest.TestCase):
    """Keep five stored objects independent while preserving generation evidence."""

    def setUp(self):
        """Isolate every test from the user's application data."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library = FittingLibrary(LibraryStore(self.root), (ZeroGainRule(), PyClarityCamfitRule()))

    def make_target(self):
        """Save a custom audiogram and independently generated target."""
        audio = self.library.duplicate(self.library.get("audiograms", "N1"), "Custom thresholds")
        value = self.library.generate_target(audio, "zero")
        target = self.library.save("targets", "Portable target", value, sources=(self.library.reference(audio),))
        return audio, target

    def make_compiled(self):
        """Save a compiled object with both source references and snapshots."""
        audio, target = self.make_target()
        calibration = self.library.get("calibrations", "eval-detector")
        value = self.library.compile(target, calibration, "left", "My compiled fitting")
        compiled = self.library.save("compiled", "My compiled fitting", value,
                                     sources=(self.library.reference(target), self.library.reference(calibration)))
        return audio, target, compiled

    def test_references_are_fixed_and_custom_audiograms_have_full_crud(self):
        """Protect all ten standards while allowing several independent custom ears."""
        self.assertEqual([e.item_id for e in self.library.list("audiograms")],
                         ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "S1", "S2", "S3"])
        for kind, item_id in (("audiograms", "N1"), ("calibrations", "eval-detector"), ("outputs", "eval-output")):
            entry = self.library.get(kind, item_id)
            with self.assertRaises(ValueError):
                self.library.save(kind, "Changed", entry.value, item_id=item_id)
            with self.assertRaises(ValueError):
                self.library.delete(kind, item_id)
            with self.assertRaises(ValueError):
                self.library.store.save(replace(entry, read_only=False))
        first = self.library.duplicate(self.library.get("audiograms", "N1"), "First")
        second = self.library.duplicate(first, "Second")
        value = replace(first.value, right_levels_db_hl=(25.,) * 10)
        updated = self.library.save("audiograms", "Updated", value, item_id=first.item_id)
        self.assertEqual(updated.revision, 2)
        reloaded = FittingLibrary(LibraryStore(self.root), ())
        self.assertEqual(reloaded.get("audiograms", first.item_id), updated)
        self.assertNotEqual(reloaded.get("audiograms", second.item_id).value, updated.value)
        self.library.delete("audiograms", first.item_id)
        with self.assertRaises(KeyError):
            self.library.get("audiograms", first.item_id)

    def test_target_links_to_audiogram_and_rule_and_preserves_old_snapshot(self):
        """Changing thresholds flags an existing target instead of rewriting it."""
        audio, target = self.make_target()
        old_hash = target.sources[0].sha256
        updated = self.library.save("audiograms", audio.name, replace(audio.value, left_levels_db_hl=(30.,) * 10), item_id=audio.item_id)
        target_after = self.library.get("targets", target.item_id)
        self.assertEqual(target_after.value.audiogram, audio.value)
        self.assertEqual(target_after.value.rule.rule_id, "zero")
        self.assertNotEqual(content_sha256(updated), old_hash)
        self.assertEqual(self.library.changed_sources(target_after), (audio.name,))
        with self.assertRaisesRegex(ValueError, "dependent"):
            self.library.delete("audiograms", audio.item_id)
        self.library.delete("targets", target.item_id)
        self.library.delete("audiograms", audio.item_id)

    def test_all_objects_round_trip_and_compiled_updates_preserve_identity(self):
        """Persist independent objects and update compiled metadata without breaking payload identity."""
        _, target, compiled = self.make_compiled()
        for kind in ("calibrations", "outputs"):
            reference = self.library.list(kind)[0]
            custom = self.library.duplicate(reference, "Custom " + kind)
            changed_value = (replace(custom.value, scope="Different setup") if kind == "calibrations"
                             else replace(custom.value, headroom_db=-20.))
            changed = self.library.save(kind, custom.name, changed_value, item_id=custom.item_id)
            self.assertEqual(entry_from_dict(entry_to_dict(changed)), changed)
            self.library.delete(kind, custom.item_id)
        updated = self.library.save("compiled", "Renamed", compiled.value, item_id=compiled.item_id, sources=compiled.sources)
        self.assertEqual(updated.value.artifact.prescription.display_name, "Renamed")
        self.assertEqual(entry_from_dict(entry_to_dict(updated)), updated)
        self.assertEqual(entry_from_dict(entry_to_dict(target)), target)
        with self.assertRaisesRegex(ValueError, "dependent"):
            self.library.delete("targets", target.item_id)
        self.library.delete("compiled", compiled.item_id)
        self.library.delete("targets", target.item_id)

    def test_eval_calibration_retains_validated_n1_bytes_and_custom_calibration_changes_mapping(self):
        """Use selected measured checkpoints rather than hidden mapper constants."""
        audio = self.library.get("audiograms", "N1")
        target = self.library.save("targets", "N1 CAMFIT", self.library.generate_target(audio, "camfit-compressive-cec1"),
                                   sources=(self.library.reference(audio),))
        calibration = self.library.get("calibrations", "eval-detector")
        reference = self.library.compile(target, calibration, "left", "Reference")
        self.assertEqual(reference.artifact.prescription.parameters, N1_PRESCRIPTION.parameters)
        custom = self.library.duplicate(calibration, "Shifted detector")
        value = replace(custom.value, calibration_id="shifted", bands=tuple(
            replace(band, detector_dbfs=tuple(v + 2 for v in band.detector_dbfs)) for band in custom.value.bands))
        custom = self.library.save("calibrations", custom.name, value, item_id=custom.item_id)
        result = self.library.compile(target, custom, "left", "Custom")
        self.assertNotEqual(result.artifact.prescription.parameters, reference.artifact.prescription.parameters)
        self.assertEqual(result.artifact.mapping.calibration_id, "shifted")
        self.assertEqual(result.calibration, custom.value)

    def test_malformed_checkpoints_and_wrong_source_links_are_rejected(self):
        """Reject unusable calibration axes and mismatched target provenance."""
        with self.assertRaises(ValueError):
            CalibrationBand(177, (-20., -20.), (45., 65.))
        audio, target = self.make_target()
        wrong = self.library.get("audiograms", "N7")
        with self.assertRaisesRegex(ValueError, "snapshot"):
            self.library.save("targets", "Wrong source", target.value, sources=(self.library.reference(wrong),))
        with self.assertRaises(ValueError):
            self.library.get("audiograms", "../../escape")

    def test_legacy_import_is_idempotent_and_does_not_restore_deleted_objects(self):
        """Split old generated artifacts once without resurrecting user deletions."""
        _, _, compiled = self.make_compiled()
        artifact = compiled.value.artifact
        other = FittingLibrary(LibraryStore(self.root / "migration"), ())
        other.import_legacy(artifact)
        other.import_legacy(artifact)
        self.assertEqual(len(other.list("targets")), 1)
        restored = other.get("compiled", artifact.artifact_id)
        self.assertEqual(restored.value.artifact, artifact)
        other.delete("compiled", restored.item_id)
        other.import_legacy(artifact)
        self.assertEqual(other.list("compiled"), ())


class OutputLoadTest(unittest.IsolatedAsyncioTestCase):
    """Use the normal fake BLE pipeline for both complete output parameters."""

    async def test_output_loads_headroom_and_complete_softclip(self):
        """Upload precisely IDs 14 and 15 using atomic per-parameter writes."""
        with tempfile.TemporaryDirectory() as directory:
            library = FittingLibrary(LibraryStore(Path(directory)), ())
            output = library.get("outputs", "eval-output")
            prescription = library.board_prescription(output)
            self.assertEqual(prescription.parameter(14).data.hex(), "000a2adb")
            self.assertEqual(prescription.payload_byte_count, 184)
            client = FakePrescriptionClient()
            result = await PrescriptionLoader().load(client, device_session(), prescription)
            self.assertEqual([(i, len(data)) for i, data in client.writes], [(14, 4), (15, 180)])
            self.assertEqual(result.parameter_count, 2)
            client = FakePrescriptionClient(fail_parameter_id=15)
            with self.assertRaises(PrescriptionLoadError) as error:
                await PrescriptionLoader().load(client, device_session(), prescription)
            self.assertEqual(error.exception.completed_parameters, 1)
