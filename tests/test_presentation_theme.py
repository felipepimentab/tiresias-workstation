"""Verify a consistent light UI with fake devices and optional preview images.

Set TIRESIAS_UI_PREVIEW_DIR when running this module to render representative
screens offscreen. All data and controller operations are local test fixtures;
no Bleak transport or physical Bluetooth adapter is constructed.
"""

import os
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
)

from test_device_discovery_screen import FakeController
from test_generated_prescriptions import N1_FREQUENCIES_HZ, N1_LEVELS_DB_HL
from tiresias_workstation.application.default_prescriptions import (
    create_default_prescription_services,
)
from tiresias_workstation.domain.fittings import Audiogram
from tiresias_workstation.presentation.main_window import MainWindow
from tiresias_workstation.presentation.theme import apply_light_theme, light_palette


class PresentationThemeTests(unittest.TestCase):
    """Exercise all screens after starting with dark system-like colors."""

    @classmethod
    def setUpClass(cls):
        """Share one GUI application without accessing the Bluetooth adapter."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        """Start each scenario with an explicitly dark inherited palette."""
        dark = QPalette()
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            for role in (
                QPalette.ColorRole.Window,
                QPalette.ColorRole.Base,
                QPalette.ColorRole.Button,
                QPalette.ColorRole.ToolTipBase,
            ):
                dark.setColor(group, role, QColor("#202124"))
        self.app.setPalette(dark)
        apply_light_theme(self.app)
        self.directory = tempfile.TemporaryDirectory()
        self.workbench, catalog = create_default_prescription_services(
            Path(self.directory.name)
        )
        self.controller = FakeController()
        self.window = MainWindow(self.controller, catalog, self.workbench)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        """Close widgets and remove the test-only prescription library."""
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def _capture(self, name: str, widget=None) -> None:
        """Optionally export a screenshot after layout and palette propagation."""
        self.app.processEvents()
        directory = os.environ.get("TIRESIAS_UI_PREVIEW_DIR")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue((widget or self.window).grab().save(str(path / name)))

    def _navigate(self, name: str) -> None:
        """Use the same sidebar actions as the user, with a fake controller."""
        self.window.findChild(QPushButton, name).click()
        self.app.processEvents()

    def test_palette_covers_active_inactive_disabled_and_popup_surfaces(self):
        """Prevent dark defaults in native controls that have no custom paint."""
        palette = light_palette()
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            for role in (
                QPalette.ColorRole.Window,
                QPalette.ColorRole.Base,
                QPalette.ColorRole.Button,
                QPalette.ColorRole.ToolTipBase,
            ):
                with self.subTest(group=group, role=role):
                    self.assertGreater(palette.color(group, role).lightness(), 240)
                    self.assertEqual(
                        self.app.palette().color(group, role), palette.color(group, role)
                    )
        fitting = self.window.audiogram_fitting_screen
        name = fitting.findChild(QLineEdit, "customPrescriptionName")
        rule = fitting.findChild(QComboBox, "prescriptionRuleSelector")
        for widget in (name, rule.view(), QMenu(self.window)):
            widget.ensurePolished()
            self.assertGreater(widget.palette().base().color().lightness(), 230)
            self.assertLess(widget.palette().text().color().lightness(), 100)

    def test_all_screens_render_with_readable_actions_at_two_window_sizes(self):
        """Render empty, populated, selected and disabled workstation states."""
        self._capture("01-devices-empty.png")
        self.controller.scan()
        self.window.device_discovery_screen._device_table.selectRow(0)
        self._capture("02-devices-found.png")
        self.controller.connect(self.controller.device.address)
        self._capture("03-board-information.png")
        self._navigate("parametersNavigationButton")
        self._capture("04-dsp-parameters.png")
        self._navigate("prescriptionsNavigationButton")
        self._capture("05-prescriptions.png")
        self._navigate("fittingNavigationButton")
        self._capture("06-fitting-empty.png")
        artifact = self.workbench.generate(
            Audiogram(N1_FREQUENCIES_HZ, N1_LEVELS_DB_HL, N1_LEVELS_DB_HL),
            rule_id="camfit-compressive-cec1", name="Listening room", ear="left",
        )
        fitting = self.window.audiogram_fitting_screen
        fitting._show_artifact(artifact)
        fitting._save_current()
        self._capture("07-fitting-saved.png")

        for width, height in ((1180, 820), (960, 680)):
            self.window.resize(width, height)
            for destination in (
                "devicesNavigationButton", "boardNavigationButton",
                "parametersNavigationButton", "prescriptionsNavigationButton",
                "fittingNavigationButton",
            ):
                self._navigate(destination)
                with self.subTest(size=(width, height), page=destination):
                    self.assertEqual(self.window.width(), width)
                    self.assertEqual(self.window.height(), height)
                    for button in self.window.findChildren(QPushButton):
                        if not button.isVisible():
                            continue
                        top_left = button.mapTo(self.window, QPoint(0, 0))
                        self.assertGreaterEqual(top_left.x(), 0)
                        self.assertGreaterEqual(top_left.y(), 0)
                        self.assertLessEqual(top_left.x() + button.width(), width)
                        self.assertLessEqual(top_left.y() + button.height(), height)
                        self.assertLessEqual(
                            button.fontMetrics().horizontalAdvance(button.text()),
                            button.width() - 12,
                        )
                if width == 960:
                    self._capture(f"compact-{destination}.png")

    def test_error_focus_combo_popup_and_confirmation_remain_light(self):
        """Cover transient widgets and keyboard focus, not just idle pages."""
        self._navigate("fittingNavigationButton")
        fitting = self.window.audiogram_fitting_screen
        name = fitting.findChild(QLineEdit, "customPrescriptionName")
        name.setFocus(Qt.FocusReason.TabFocusReason)
        fitting._show_message("Enter numeric thresholds for both ears.", error=True)
        self.app.processEvents()
        message = fitting.findChild(QLabel, "fittingMessage")
        self.assertEqual(message.palette().windowText().color().name(), "#b42318")
        self._capture("08-fitting-validation.png")
        rule = fitting.findChild(QComboBox, "prescriptionRuleSelector")
        rule.showPopup()
        self._capture("09-rule-popup.png", rule.view().window())
        rule.hidePopup()
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Delete custom prescription")
        dialog.setText('Delete "Listening room" from this workstation?')
        dialog.setInformativeText("Exported copies are not affected.")
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.show()
        self.app.processEvents()
        self.assertGreater(dialog.palette().window().color().lightness(), 240)
        self._capture("10-confirmation.png", dialog)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
