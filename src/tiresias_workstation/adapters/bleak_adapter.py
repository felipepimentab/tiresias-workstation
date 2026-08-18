"""Adapt Bleak's native Bluetooth objects to workstation domain types.

``BleakDeviceTransport`` must be used from one asyncio event loop. The Qt-facing
controller guarantees that ownership and translates its results into Qt
signals; this module deliberately contains no Qt dependencies.
"""

import asyncio
from collections.abc import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from tiresias_workstation.domain.devices import DiscoveredDevice


class BleakDeviceTransport:
    """Discover and connect to BLE devices through the native OS backend.

    The transport retains the :class:`~bleak.backends.device.BLEDevice` objects
    returned by the latest scan. Passing those objects back to Bleak avoids an
    implicit second discovery during connection, which is both slower and less
    reliable on some platforms.

    Attributes:
        _devices: Native device handles indexed by their platform identifier.
        _client: Connected Bleak client, or ``None`` while disconnected.
    """

    def __init__(self) -> None:
        """Initialize an idle transport with no discovered devices."""
        self._devices: dict[str, BLEDevice] = {}
        self._client: BleakClient | None = None

    async def scan(
        self,
        on_device: Callable[[DiscoveredDevice], None],
        *,
        timeout: float,
    ) -> list[DiscoveredDevice]:
        """Collect BLE advertisements for a bounded period.

        Repeated advertisements update the stored snapshot and are forwarded
        immediately so the UI can present live RSSI and metadata changes.

        Args:
            on_device: Callback receiving each advertisement snapshot.
            timeout: Number of seconds for which scanning remains active.

        Returns:
            One latest snapshot per address, sorted by name and signal strength.

        Raises:
            bleak.exc.BleakError: If the platform adapter is unavailable,
                permission is denied, or scanning otherwise fails.
        """
        discovered: dict[str, DiscoveredDevice] = {}
        self._devices = {}

        def advertisement_received(
            device: BLEDevice, advertisement: AdvertisementData
        ) -> None:
            """Normalize one backend advertisement and publish its snapshot."""
            snapshot = DiscoveredDevice(
                address=device.address,
                name=advertisement.local_name or device.name,
                rssi=advertisement.rssi,
                service_uuids=tuple(
                    sorted({uuid.lower() for uuid in advertisement.service_uuids})
                ),
            )
            self._devices[device.address] = device
            discovered[device.address] = snapshot
            on_device(snapshot)

        async with BleakScanner(detection_callback=advertisement_received):
            await asyncio.sleep(timeout)

        return sorted(
            discovered.values(),
            key=lambda device: (
                device.name is None,
                (device.name or "").casefold(),
                -device.rssi,
                device.address,
            ),
        )

    async def connect(
        self,
        address: str,
        on_disconnected: Callable[[str], None],
        *,
        timeout: float,
    ) -> None:
        """Connect to a device retained from the most recent scan.

        Any existing connection is closed before the new attempt. The client is
        stored only after Bleak confirms it remains connected.

        Args:
            address: Platform identifier of the target device.
            on_disconnected: Callback receiving ``address`` after link loss or
                an explicit disconnect.
            timeout: Maximum connection duration in seconds.

        Raises:
            ValueError: If no native handle exists for ``address``.
            TimeoutError: If the connection attempt exceeds ``timeout``.
            ConnectionError: If Bleak returns without an active connection.
            bleak.exc.BleakError: If the backend rejects the connection.
        """
        device = self._devices.get(address)
        if device is None:
            raise ValueError("Device is no longer available. Scan again and retry.")

        await self.disconnect()

        client = BleakClient(
            device,
            disconnected_callback=lambda _client: on_disconnected(address),
            timeout=timeout,
        )
        try:
            async with asyncio.timeout(timeout):
                await client.connect()
            if not client.is_connected:
                raise ConnectionError(
                    "The operating system did not establish a connection."
                )
        except BaseException:
            # Cancellation derives from BaseException on supported Python
            # versions. Always release a partially connected native client
            # before propagating cancellation or the original backend error.
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:
                pass
            raise

        self._client = client

    async def disconnect(self) -> None:
        """Close and forget the active Bleak client.

        Clearing ``_client`` in ``finally`` prevents a failed backend teardown
        from leaving a stale client available to later operations.
        """
        client = self._client
        if client is None:
            return

        try:
            if client.is_connected:
                await client.disconnect()
        finally:
            self._client = None
