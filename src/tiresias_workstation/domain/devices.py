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
        is_tiresias: Whether the custom Tiresias service was advertised. This
            identity does not depend on the mutable local device name.
    """

    address: str
    name: str | None
    rssi: int
    service_uuids: tuple[str, ...] = ()
    is_tiresias: bool = False


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

    async def read_characteristic(self, characteristic_uuid: str) -> bytes:
        """Read a GATT characteristic from the active connection.

        Args:
            characteristic_uuid: Canonical 128-bit characteristic UUID.

        Returns:
            Characteristic value copied into immutable bytes.

        Raises:
            ConnectionError: If no device is connected.
            Exception: If the platform Bluetooth backend rejects the read.
        """

    async def write_characteristic(
        self,
        characteristic_uuid: str,
        value: bytes,
        *,
        response: bool,
    ) -> None:
        """Write a GATT characteristic on the active connection.

        Args:
            characteristic_uuid: Canonical 128-bit characteristic UUID.
            value: Complete characteristic payload.
            response: Whether ATT write-with-response is required.
        """

    async def start_notifications(
        self,
        characteristic_uuid: str,
        callback: Callable[[bytes], None],
    ) -> None:
        """Subscribe to notifications or indications for a characteristic.

        Args:
            characteristic_uuid: Canonical 128-bit characteristic UUID.
            callback: Callback invoked on the owning asyncio thread for every
                received value.
        """

    async def stop_notifications(self, characteristic_uuid: str) -> None:
        """Remove an active characteristic subscription if connected.

        Args:
            characteristic_uuid: Canonical 128-bit characteristic UUID.
        """
