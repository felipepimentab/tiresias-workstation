"""Exercise the local audiogram fitting workflow with an injected rule."""

import tempfile
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from tests.test_generated_prescriptions import ZeroGainRule
from tiresias_workstation.adapters.json_prescription_store import (
    JsonPrescriptionStore,
)
from tiresias_workstation.adapters.sigma_dsp_mapper import SigmaDspMapper
from tiresias_workstation.application.prescription_workbench import (
    PrescriptionWorkbench,
)
from tiresias_workstation.presentation.audiogram_fitting_screen import (
    AudiogramFittingScreen,
)


class AudiogramFittingScreenTests(unittest.TestCase):
    """Keep Qt presentation separate from rule, mapping, and storage details."""

    @classmethod
    def setUpClass(cls):
        """Create one offscreen-compatible Qt application."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        """Build an isolated workbench and screen for each test."""
        self.directory = tempfile.TemporaryDirectory()
        self.workbench = PrescriptionWorkbench(
            (ZeroGainRule(),),
            SigmaDspMapper(),
            JsonPrescriptionStore(Path(self.directory.name)),
        )
        self.screen = AudiogramFittingScreen(self.workbench)

    def tearDown(self):
        """Release the widget and temporary local catalog."""
        self.screen.close()
        self.directory.cleanup()

    def test_generates_previews_and_saves_a_named_custom_prescription(self):
        """Drive the user-visible fitting path without pyClarity or BLE."""
        name = self.screen.findChild(QLineEdit, "customPrescriptionName")
        generate = self.screen.findChild(QPushButton, "generatePrescriptionButton")
        save = self.screen.findChild(QPushButton, "saveGeneratedPrescriptionButton")
        target = self.screen.findChild(QTableWidget, "prescriptionTargetTable")
        saved = self.screen.findChild(QTableWidget, "savedPrescriptionTable")
        emitted: list[str] = []
        self.screen.prescription_saved.connect(emitted.append)

        name.setText("Lab fitting")
        generate.click()
        deadline = time.monotonic() + 5.0
        while not save.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertEqual(target.rowCount(), 8)
        self.assertEqual(target.item(0, 1).text(), "0.00")
        self.assertTrue(save.isEnabled())
        save.click()

        self.assertEqual(saved.rowCount(), 1)
        self.assertEqual(saved.item(0, 0).text(), "Lab fitting")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(len(self.workbench.list_saved()), 1)

    def test_saved_artifact_can_be_inspected_exported_and_deleted(self):
        """Round-trip a saved selection and confirm deletion through the UI."""
        artifact = self.workbench.generate(
            self.screen._read_audiogram(),
            rule_id="zero", name="Saved fitting", ear="right",
        )
        self.workbench.save(artifact)
        self.screen.refresh_saved(select_artifact_id=artifact.artifact_id)
        name = self.screen.findChild(QLineEdit, "customPrescriptionName")
        self.assertEqual(name.text(), "Saved fitting")
        export = self.screen.findChild(QPushButton, "exportSavedPrescriptionButton")
        # Keep export outside the managed store so it survives catalog deletion.
        with tempfile.TemporaryDirectory() as export_directory:
            export_path = Path(export_directory) / "shared.json"
            with patch(
                "tiresias_workstation.presentation.audiogram_fitting_screen."
                "QFileDialog.getSaveFileName",
                return_value=(str(export_path), "JSON files (*.json)"),
            ):
                export.click()
            self.assertTrue(export_path.is_file())
            delete = self.screen.findChild(
                QPushButton, "deleteSavedPrescriptionButton"
            )
            emitted: list[str] = []
            self.screen.prescription_deleted.connect(emitted.append)
            with patch(
                "tiresias_workstation.presentation.audiogram_fitting_screen."
                "QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                delete.click()
            self.assertEqual(len(self.workbench.list_saved()), 1)
            with patch(
                "tiresias_workstation.presentation.audiogram_fitting_screen."
                "QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                delete.click()
            self.assertEqual(self.workbench.list_saved(), ())
            self.assertEqual(emitted, [artifact.artifact_id])
            self.assertTrue(export_path.is_file())

    def test_generation_error_restores_controls_without_saving(self):
        """Report background failures while leaving the local catalog untouched."""
        name = self.screen.findChild(QLineEdit, "customPrescriptionName")
        generate = self.screen.findChild(QPushButton, "generatePrescriptionButton")
        message = self.screen.findChild(QLabel, "fittingMessage")
        name.setText("Failed fitting")
        with patch.object(self.workbench, "generate", side_effect=ValueError("Bad fit")):
            generate.click()
            deadline = time.monotonic() + 5.0
            while not generate.isEnabled() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
        self.assertTrue(generate.isEnabled())
        self.assertTrue(name.isEnabled())
        self.assertEqual(message.text(), "Bad fit")
        self.assertEqual(self.workbench.list_saved(), ())


if __name__ == "__main__":
    unittest.main()
