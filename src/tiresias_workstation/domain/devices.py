"""Define platform-neutral Bluetooth device types.

This module forms the domain boundary between the user interface and a concrete
Bluetooth implementation.  Keeping these types free of Qt and Bleak allows the
application workflow to be tested without an operating-system Bluetooth stack.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """Represent the latest advertisement received from a BLE peripheral.

    Attributes:
        address: Platform-provided device identifier. This is commonly a MAC
            address on Linux and Windows, and a UUID on macOS.
        name: Most recent advertised local name, or ``None`` when the device
            did not publish one.
        rssi: Received signal strength indicator in dBm. Values closer to zero
            generally indicate a stronger signal.
        service_uuids: Normalized, lowercase service UUIDs included in the
            advertisement.
    """

    address: str
    name: str | None
    rssi: int
    service_uuids: tuple[str, ...] = ()


class DeviceTransport(Protocol):
    """Describe the Bluetooth operations required by the application.

    Implementations own any backend-specific device handles. Callers interact
    only with :class:`DiscoveredDevice` snapshots and stable string identifiers.
    """

    async def scan(
        self,
        on_device: Callable[[DiscoveredDevice], None],
        *,
        timeout: float,
    ) -> list[DiscoveredDevice]:
        """Scan for nearby advertisers and report updates as they arrive.

        Args:
            on_device: Callback invoked for every new or updated advertisement.
                A device may be reported more than once during a scan.
            timeout: Number of seconds to keep the scanner active.

        Returns:
            The latest snapshot of each unique device, in display order.

        Raises:
            Exception: If the platform Bluetooth backend cannot scan. Concrete
                implementations should preserve the original backend exception.
        """

    async def connect(
        self,
        address: str,
        on_disconnected: Callable[[str], None],
        *,
        timeout: float,
    ) -> None:
        """Connect to a device found by the most recent scan.

        Args:
            address: Platform identifier from a discovered device.
            on_disconnected: Callback invoked if the active connection closes.
            timeout: Maximum number of seconds allowed for the connection.

        Raises:
            ValueError: If ``address`` was not present in the latest scan.
            Exception: If the platform Bluetooth backend cannot connect.
        """

    async def disconnect(self) -> None:
        """Disconnect the active device, if any.

        The method is idempotent: calling it without an active client has no
        effect.
        """
