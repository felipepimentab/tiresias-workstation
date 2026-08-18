"""Define the top-level Tiresias Workstation window."""

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from tiresias_workstation.ble_controller import BleController
from tiresias_workstation.device_discovery_screen import DeviceDiscoveryScreen


class MainWindow(QMainWindow):
    """Own application-level services and the active workstation screen."""

    def __init__(self, controller: BleController | None = None) -> None:
        """Initialize the workstation window.

        Args:
            controller: Optional controller for dependency injection. A real
                :class:`BleController` is created when omitted.
        """
        super().__init__()

        self._controller = controller or BleController()

        self.setWindowTitle("Tiresias Workstation")
        self.resize(960, 660)
        self.setMinimumSize(760, 520)

        self.device_discovery_screen = DeviceDiscoveryScreen(self._controller)
        self.setCentralWidget(self.device_discovery_screen)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Release Bluetooth resources before Qt destroys the window.

        Args:
            event: Qt close event passed to the base window implementation.
        """
        self._controller.shutdown()
        super().closeEvent(event)
