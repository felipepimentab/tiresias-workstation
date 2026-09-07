"""Exercise five-library editing and board-load dispatch with offscreen Qt."""

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QTableWidgetItem
from tiresias_workstation.adapters.library_store import LibraryStore
from tiresias_workstation.application.fitting_library import FittingLibrary
from tiresias_workstation.presentation.fitting_library_screen import FittingLibraryScreen, LibraryEditor
from tiresias_workstation.presentation.theme import apply_light_theme
from test_generated_prescriptions import ZeroGainRule
from test_device_discovery_screen import FakeController
from test_ble_controller import device_session


class LibraryScreenTest(unittest.TestCase):
    """Verify typed editing, generation and load actions without physical BLE."""

    @classmethod
    def setUpClass(cls):
        """Use one application with the production light theme."""
        cls.app = QApplication.instance() or QApplication([])
        apply_light_theme(cls.app)

    def setUp(self):
        """Keep every local mutation inside an isolated directory."""
        self.directory = tempfile.TemporaryDirectory()
        self.library = FittingLibrary(LibraryStore(Path(self.directory.name)), (ZeroGainRule(),))
        self.controller = FakeController()
        self.screen = FittingLibraryScreen(self.library, self.controller)
        self.addCleanup(self.screen.close)
        self.addCleanup(self.directory.cleanup)

    def wait_generation(self, editor):
        """Process Qt worker delivery while retaining the dialog owner."""
        deadline = time.monotonic() + 5
        while editor._task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIsNone(editor._task)
        self.assertIsNotNone(editor.value, editor.message.text())

    def test_standard_view_is_read_only_and_custom_audiograms_can_be_edited(self):
        """Protect references at the UI and repository boundaries."""
        self.assertEqual(self.screen.items.count(), 10)
        self.assertFalse(self.screen.edit_button.isEnabled())
        reference = self.library.get("audiograms", "N1")
        view = LibraryEditor(self.library, "audiograms", reference)
        self.assertTrue(view.name.isReadOnly())
        self.assertTrue(view.buttons.button(QDialogButtonBox.StandardButton.Save).isHidden())
        view.close()
        create = LibraryEditor(self.library, "audiograms")
        create.name.setText("Custom ears")
        create.audio_table.setItem(0, 2, QTableWidgetItem("35"))
        create._save()
        self.assertIsNotNone(create.saved_entry, create.message.text())
        item = create.saved_entry
        self.assertEqual(item.value.right_levels_db_hl[0], 35)
        edit = LibraryEditor(self.library, "audiograms", item)
        edit.name.setText("Updated ears")
        edit._save()
        self.assertEqual(edit.saved_entry.item_id, item.item_id)
        self.assertEqual(edit.saved_entry.revision, 2)

    def test_generate_save_compile_and_load_with_independent_sources(self):
        """Drive both stages through the worker and the shared transfer controller."""
        target = LibraryEditor(self.library, "targets")
        target.name.setText("Portable target")
        target._generate_target()
        self.wait_generation(target)
        target._save()
        self.assertIsNotNone(target.saved_entry, target.message.text())
        compiled = LibraryEditor(self.library, "compiled")
        compiled.name.setText("Right ear compiled")
        compiled.ear.setCurrentText("right")
        compiled._compile()
        self.wait_generation(compiled)
        compiled._save()
        self.assertIsNotNone(compiled.saved_entry, compiled.message.text())
        self.assertEqual(compiled.saved_entry.sources[0].item_id, target.saved_entry.item_id)
        self.screen.close()
        self.screen = FittingLibraryScreen(self.library, self.controller, kind="compiled")
        self.addCleanup(self.screen.close)
        self.screen.refresh(select_id=compiled.saved_entry.item_id)
        self.assertFalse(self.screen.load_button.isEnabled())
        self.controller.session_loaded.emit(device_session())
        self.screen.load_button.click()
        self.assertEqual(len(self.controller.prescription_loads[-1].parameters), 11)
        self.assertIn("11 parameters", self.screen.status.text())
        output_screen = FittingLibraryScreen(self.library, self.controller, kind="outputs")
        self.addCleanup(output_screen.close)
        self.screen = output_screen
        self.controller.session_loaded.emit(device_session())
        self.screen.load_button.click()
        self.assertEqual([int(p.parameter_id) for p in self.controller.prescription_loads[-1].parameters], [14, 15])
        self.assertIn("2 parameters", self.screen.status.text())

    def test_only_board_objects_have_transfer_controls(self):
        """Keep reference pages free of even disabled load actions."""
        for kind in ("audiograms", "targets", "calibrations", "compiled", "outputs"):
            page = FittingLibraryScreen(self.library, self.controller, kind=kind)
            self.addCleanup(page.close)
            self.assertEqual(page.kind, kind)
            self.assertEqual(page.load_button is not None, kind in ("compiled", "outputs"))
            self.assertEqual(page.transfer_panel is not None, kind in ("compiled", "outputs"))
            if page.load_button is None:
                page._load()
        self.assertEqual(self.controller.prescription_loads, [])

    def test_transfer_cards_share_busy_state_and_clear_disconnected_status(self):
        """Prevent overlapping loads and keep online/offline instructions accurate."""
        compiled = FittingLibraryScreen(self.library, self.controller, kind="compiled")
        output = FittingLibraryScreen(self.library, self.controller, kind="outputs")
        self.addCleanup(compiled.close)
        self.addCleanup(output.close)
        self.controller.session_loaded.emit(device_session())
        prescription = self.library.board_prescription(self.library.get("outputs", "eval-output"))
        self.controller.prescription_load_started.emit(prescription)
        self.assertFalse(output.load_button.isEnabled())
        self.assertFalse(compiled.load_button.isEnabled())
        self.assertIn("Another board transfer", compiled.status.text())
        output._load()
        self.assertEqual(self.controller.prescription_loads, [])
        self.controller.prescription_load_failed.emit(prescription.profile_id, "Connection lost during output load")
        self.assertIn("Connection lost", output.status.text())
        self.controller.disconnected.emit("fake")
        self.assertFalse(output.load_button.isEnabled())
        self.assertIn("Connect a compatible board", output.status.text())

    def test_delete_toasts_explain_dependencies_and_confirm_success(self):
        """Report blocked deletion without changing sources or compiled payloads."""
        audio = self.library.duplicate(self.library.get("audiograms", "N1"), "Custom ears")
        target = self.library.save("targets", "My target", self.library.generate_target(audio, "zero"),
                                   sources=(self.library.reference(audio),))
        calibration = self.library.get("calibrations", "eval-detector")
        compiled = self.library.save("compiled", "My DSP object",
            self.library.compile(target, calibration, "left", "My DSP object"),
            sources=(self.library.reference(target), self.library.reference(calibration)))
        for entry, dependent in ((audio, target), (target, compiled)):
            page = FittingLibraryScreen(self.library, self.controller, kind=entry.kind)
            self.addCleanup(page.close)
            page.resize(720, 580)
            page.show()
            page.refresh(select_id=entry.item_id)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                page.delete_button.click()
            self.assertFalse(page.toast.isHidden())
            self.assertIn("Could not delete", page.toast.text())
            self.assertIn(dependent.name, page.toast.text())
            self.assertEqual(self.library.get(entry.kind, entry.item_id), entry)
            self.assertTrue(page._toast_timer.isActive())
            page._toast_timer.timeout.emit()
            self.assertTrue(page.toast.isHidden())
        self.assertEqual(self.library.get("compiled", compiled.item_id), compiled)
        self.library.delete("compiled", compiled.item_id)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            page.delete_button.click()
        self.assertEqual(self.library.get("targets", target.item_id), target)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            page.delete_button.click()
        self.assertEqual(page.toast.text(), 'Deleted "My target".')
        self.assertEqual(page.items.count(), 0)
        with self.assertRaises(KeyError):
            self.library.get("targets", target.item_id)

    def test_custom_calibration_and_output_editors_persist_values(self):
        """Save user changes without modifying packaged Eval defaults."""
        calibration = LibraryEditor(self.library, "calibrations")
        calibration.name.setText("Measured custom board")
        calibration.scope.setText("Custom board fixed analogue gains")
        calibration._save()
        self.assertIsNotNone(calibration.saved_entry, calibration.message.text())
        self.assertFalse(calibration.saved_entry.read_only)
        output = LibraryEditor(self.library, "outputs")
        output.name.setText("Custom output")
        output.output_fields["headroom_db"].setValue(-20)
        output._save()
        self.assertIsNotNone(output.saved_entry, output.message.text())
        self.assertEqual(output.saved_entry.value.headroom_db, -20)
        self.assertEqual(self.library.get("outputs", "eval-output").value.headroom_db, -22)
