"""Own the workstation's light palette and shared visual language.

Screens contain layout and behavior, not independent color themes. Explicit
palette roles cover native controls, editors, popups, and disabled/inactive
states that a stylesheet alone misses. The platform QStyle, system typeface,
window decorations, scrollbars, menus, and file dialogs are retained.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


def light_palette() -> QPalette:
    """Return a complete light palette independent of the system appearance."""
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#ffffff",
        QPalette.ColorRole.WindowText: "#242426",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#fafafa",
        QPalette.ColorRole.Text: "#242426",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#242426",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#f5f5f5",
        QPalette.ColorRole.Mid: "#dedee0",
        QPalette.ColorRole.Dark: "#b7b7bc",
        QPalette.ColorRole.Shadow: "#85858b",
        QPalette.ColorRole.Highlight: "#dceaff",
        QPalette.ColorRole.HighlightedText: "#242426",
        QPalette.ColorRole.Link: "#0066cc",
        QPalette.ColorRole.LinkVisited: "#6354a4",
        QPalette.ColorRole.ToolTipBase: "#fafafa",
        QPalette.ColorRole.ToolTipText: "#242426",
        QPalette.ColorRole.PlaceholderText: "#76767c",
        QPalette.ColorRole.Accent: "#007aff",
    }
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        for role, color in colors.items():
            palette.setColor(group, role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#929298"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor("#f5f5f5")
    )
    palette.setColor(
        QPalette.ColorGroup.Inactive,
        QPalette.ColorRole.Highlight,
        QColor("#ededee"),
    )
    return palette


def apply_light_theme(app: QApplication) -> None:
    """Apply the shared appearance before constructing application windows.

    Args:
        app: GUI application owned by the entry point. Call on the UI thread.

    The color-scheme hint requests light native chrome on supported platforms.
    Explicit palette entries also protect controls when that hint is ignored.
    No replacement QStyle is installed, preserving macOS-native affordances.
    """
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(light_palette())
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    app.setFont(font)
    app.setStyleSheet(_STYLE_SHEET)


_STYLE_SHEET = """
QWidget { color: #242426; }
QWidget:disabled { color: #929298; }
QMainWindow, QDialog, QMessageBox, #applicationShell,
#deviceDiscoveryScreen, #deviceControlScreen, #prescriptionScreen,
#audiogramFittingScreen, #boardInformationPage, #parameterPage {
    background: #ffffff;
}
QLabel { background: transparent; }
#pageTitle, #controlTitle, #prescriptionTitle, #fittingTitle {
    font-size: 24px; font-weight: 600;
}
#pageSubtitle, #controlSummary, #prescriptionSubtitle, #fittingSubtitle,
#resultSummary, #messageLabel, #parameterMessage, #prescriptionMessage,
#selectedPrescriptionDetails, #prescriptionProgressCount, #resultDetails,
#fittingMessage { color: #68686e; font-size: 12px; }
#messageLabel[error="true"], #parameterMessage[error="true"],
#prescriptionMessage[error="true"], #fittingMessage[error="true"] {
    color: #b42318;
}
#selectionLabel, QLabel[role="fieldLabel"] {
    color: #68686e; font-size: 12px;
}
#selectionDetail, #selectedParameter { font-weight: 500; }
#selectedPrescriptionTitle, #fittingCardTitle, #savedPrescriptionTitle {
    font-size: 14px; font-weight: 600;
}

#sidebar {
    background: #f5f5f5; border: none; border-right: 1px solid #e7e7e8;
}
#sidebarBrand { font-size: 15px; font-weight: 600; padding: 6px 10px 16px; }
#sidebarSectionLabel {
    color: #808086; font-size: 10px; font-weight: 600;
    padding: 18px 10px 6px;
}
#sidebar QPushButton {
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    text-align: left; padding: 0 10px; min-height: 34px; font-weight: 400;
}
#sidebar QPushButton:hover:enabled { background: #ededed; }
#sidebar QPushButton[selected="true"] {
    background: #e8e8e8; color: #202022; font-weight: 500;
}
#sidebar QPushButton:disabled { background: transparent; color: #96969b; }
#sidebar QPushButton:focus { border-color: #80b2ed; }
#productBoundary {
    border-top: 1px solid #e4e4e5; color: #808086; font-size: 11px;
    padding: 14px 10px 4px;
}

#deviceCard, #actionCard, #parameterEditor, #selectedPrescriptionCard,
#fittingCard {
    background: #ffffff; border: 1px solid #e2e2e4; border-radius: 9px;
}
#controlPages { border: none; background: #ffffff; }
#boardInformationPage { border: 1px solid #e2e2e4; border-radius: 9px; }
#statusBadge, #prescriptionConnectionBadge {
    background: #f3f3f4; color: #68686e; border-radius: 10px;
    font-size: 11px; padding: 5px 10px;
}
#statusBadge[connectionState="working"] { color: #925600; background: #fff6e5; }
#statusBadge[connectionState="connected"] { color: #237346; background: #edf6ef; }

QPushButton {
    background: #ffffff; color: #303034; border: 1px solid #d8d8db;
    border-radius: 6px; min-height: 30px; padding: 0 12px; font-weight: 500;
}
QPushButton:hover { background: #f5f5f6; border-color: #c8c8cc; }
QPushButton:pressed { background: #ebebed; }
QPushButton:focus { border-color: #80b2ed; }
#scanButton, #connectButton, #loadPrescriptionButton,
#generatePrescriptionButton, #saveGeneratedPrescriptionButton,
#writeParameterButton {
    background: #272729; color: #ffffff; border-color: #272729;
}
#scanButton:hover, #connectButton:hover, #loadPrescriptionButton:hover,
#generatePrescriptionButton:hover, #saveGeneratedPrescriptionButton:hover,
#writeParameterButton:hover { background: #424244; border-color: #424244; }
#scanButton:pressed, #connectButton:pressed, #loadPrescriptionButton:pressed,
#generatePrescriptionButton:pressed, #saveGeneratedPrescriptionButton:pressed,
#writeParameterButton:pressed { background: #161618; }
#scanButton:focus, #connectButton:focus, #loadPrescriptionButton:focus,
#generatePrescriptionButton:focus, #saveGeneratedPrescriptionButton:focus,
#writeParameterButton:focus { border-color: #80b2ed; }
QPushButton:disabled, #scanButton:disabled, #connectButton:disabled,
#loadPrescriptionButton:disabled, #generatePrescriptionButton:disabled,
#saveGeneratedPrescriptionButton:disabled, #writeParameterButton:disabled {
    background: #f3f3f4; color: #929298; border-color: #e7e7e9;
}
#deleteSavedPrescriptionButton { color: #b42318; }
#deleteSavedPrescriptionButton:disabled { color: #929298; }

QLineEdit {
    background: #ffffff; color: #242426; border: 1px solid #d8d8db;
    border-radius: 6px; min-height: 28px; padding: 1px 8px;
    selection-background-color: #dceaff; selection-color: #242426;
}
QLineEdit:focus { border-color: #80b2ed; }
QLineEdit:disabled { background: #f7f7f8; color: #929298; border-color: #e7e7e9; }
/* Keep native combo-box arrows, popup behavior and platform scrollbars. */
QComboBox { min-height: 30px; padding: 0 6px; }
QComboBox QAbstractItemView {
    background: #ffffff; color: #242426;
    selection-background-color: #eaeaec; selection-color: #242426;
}
QTableView {
    background: #ffffff; alternate-background-color: #fafafa;
    color: #242426; border: 1px solid #e2e2e4; border-radius: 7px;
    gridline-color: #eeeeef; font-size: 12px;
    selection-background-color: #ededee; selection-color: #202022;
}
QTableView::item { padding: 4px 7px; border: none; }
QTableView::item:selected { background: #ededee; color: #202022; }
QTableView::item:focus { border: 1px solid #80b2ed; }
QTableView:disabled { color: #929298; background: #fafafa; }
QTableView QLineEdit { border-radius: 2px; min-height: 0; padding: 0 3px; }
QHeaderView { background: #fafafa; }
QHeaderView::section {
    background: #fafafa; color: #68686e; border: none;
    border-bottom: 1px solid #e7e7e9; padding: 7px;
    font-size: 11px; font-weight: 500;
}
QTableCornerButton::section { background: #fafafa; border: none; }
#deviceTable { border: none; }
QProgressBar {
    background: #ededee; border: none; border-radius: 3px;
    min-height: 5px; max-height: 5px;
}
QProgressBar::chunk { background: #727278; border-radius: 3px; }
QSplitter::handle { background: #ffffff; }
QSplitter::handle:hover { background: #f1f1f2; }
"""
