"""Coordinate asynchronous Bluetooth work for Qt widgets.

Qt owns the main thread while Bleak expects a continuously running asyncio
event loop. :class:`BleController` bridges those models by owning one daemon
thread and one asyncio loop for the lifetime of the window. Results cross the
thread boundary exclusively through Qt signals.
"""

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from concurrent.futures import CancelledError as FutureCancelledError
from threading import Event, Lock, Thread
from typing import Any

from PySide6.QtCore import QObject, Signal

from tiresias_workstation.adapters.bleak_adapter import BleakDeviceTransport
from tiresias_workstation.domain.devices import DeviceTransport, DiscoveredDevice

# Factories make the controller independently testable with an in-memory
# transport while ensuring the real Bleak transport is created on its own loop.
TransportFactory = Callable[[], DeviceTransport]
OperationFactory = Callable[[DeviceTransport], Coroutine[Any, Any, Any]]


class BleController(QObject):
    """Run Bleak on a dedicated asyncio thread and publish Qt signals.

    Only one scan, connection, or disconnection operation may run at a time.
    Public methods are synchronous scheduling requests: they return immediately
    and report eventual results through signals.

    Signals:
        device_discovered(object): Emits a :class:`DiscoveredDevice` for each
            advertisement received during a scan.
        scan_started(): Emits after a scan is accepted for execution.
        scan_finished(object): Emits the final ``list[DiscoveredDevice]``.
        scan_failed(str): Emits a user-displayable backend error.
        connection_started(str): Emits the target device address.
        connection_succeeded(str): Emits the connected device address.
        connection_failed(str, str): Emits the address and error message for a
            failed connection or disconnection operation.
        disconnection_started(str): Emits the connected device address.
        disconnected(str): Emits once when the active connection closes.

    Attributes:
        _state_lock: Protects controller state shared by the Qt and BLE threads.
        _ready: Indicates that the BLE event loop and transport are available.
        _active_future: The sole operation currently scheduled on the BLE loop.
        _connected_address: Address whose connection has been confirmed.
        _closed: Prevents new work and suppresses signals during shutdown.
    """

    device_discovered = Signal(object)
    scan_started = Signal()
    scan_finished = Signal(object)
    scan_failed = Signal(str)

    connection_started = Signal(str)
    connection_succeeded = Signal(str)
    connection_failed = Signal(str, str)
    disconnection_started = Signal(str)
    disconnected = Signal(str)

    def __init__(
        self,
        *,
        transport_factory: TransportFactory | None = None,
        scan_timeout: float = 5.0,
        connection_timeout: float = 15.0,
    ) -> None:
        """Create and start the background Bluetooth worker.

        Args:
            transport_factory: Optional zero-argument factory used to create the
                transport inside the BLE thread. Defaults to
                :class:`BleakDeviceTransport`.
            scan_timeout: Duration of each discovery scan in seconds.
            connection_timeout: Maximum duration of a connection attempt in
                seconds.

        Raises:
            RuntimeError: If the worker does not become ready within two seconds
                or if transport construction fails.
        """
        super().__init__()
        self._transport_factory = transport_factory or BleakDeviceTransport
        self._scan_timeout = scan_timeout
        self._connection_timeout = connection_timeout

        self._state_lock = Lock()
        self._ready = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._transport: DeviceTransport | None = None
        self._startup_error: BaseException | None = None
        self._active_future: Future[Any] | None = None
        self._connected_address: str | None = None
        self._closed = False

        self._thread = Thread(
            target=self._run_event_loop,
            name="tiresias-ble",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=2.0):
            raise RuntimeError("The Bluetooth worker did not start.")
        if self._startup_error is not None:
            raise RuntimeError(
                "The Bluetooth worker could not start."
            ) from self._startup_error

    def scan(self) -> bool:
        """Request a discovery scan.

        Returns:
            ``True`` if the scan was scheduled, or ``False`` if the controller
            is closed or another operation is already active.
        """
        future = self._schedule(
            lambda transport: transport.scan(
                self.device_discovered.emit,
                timeout=self._scan_timeout,
            )
        )
        if future is None:
            return False

        self.scan_started.emit()
        future.add_done_callback(self._scan_completed)
        return True

    def connect(self, address: str) -> bool:
        """Request a connection to a discovered device.

        Args:
            address: Platform identifier reported by the latest scan.

        Returns:
            ``True`` if the operation was scheduled, otherwise ``False``.
        """
        future = self._schedule(
            lambda transport: transport.connect(
                address,
                self._transport_disconnected,
                timeout=self._connection_timeout,
            )
        )
        if future is None:
            return False

        self.connection_started.emit(address)
        future.add_done_callback(
            lambda completed: self._connection_completed(address, completed)
        )
        return True

    def disconnect(self) -> bool:
        """Request disconnection of the active device.

        Returns:
            ``True`` if disconnection was scheduled, or ``False`` when no
            confirmed connection exists or another operation is active.
        """
        with self._state_lock:
            address = self._connected_address
        if address is None:
            return False

        future = self._schedule(lambda transport: transport.disconnect())
        if future is None:
            return False

        self.disconnection_started.emit(address)
        future.add_done_callback(
            lambda completed: self._disconnection_completed(address, completed)
        )
        return True

    def shutdown(self) -> None:
        """Stop outstanding work and release the native BLE connection.

        This idempotent method is intended for ``QMainWindow.closeEvent``. It
        waits briefly for an orderly disconnect, then stops and joins the event
        loop thread. Remaining tasks are cancelled during loop teardown.
        """
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            active_future = self._active_future
            loop = self._loop
            transport = self._transport

        if active_future is not None:
            active_future.cancel()

        if loop is not None and transport is not None and loop.is_running():
            # Transport methods must run on the loop that owns the native Bleak
            # objects, even though shutdown itself is called by the Qt thread.
            cleanup = asyncio.run_coroutine_threadsafe(transport.disconnect(), loop)
            try:
                cleanup.result(timeout=3.0)
            except Exception:
                # The loop teardown below also cancels any remaining backend work.
                pass
            loop.call_soon_threadsafe(loop.stop)

        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _run_event_loop(self) -> None:
        """Create, run, and finally drain the BLE thread's asyncio loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            transport = self._transport_factory()
        except BaseException as error:
            self._startup_error = error
            self._ready.set()
            loop.close()
            return

        with self._state_lock:
            self._loop = loop
            self._transport = transport
        self._ready.set()

        try:
            loop.run_forever()
        finally:
            # Cancelling and gathering pending tasks lets async context managers
            # (notably BleakScanner) release their native resources before close.
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            asyncio.set_event_loop(None)
            loop.close()

    def _schedule(self, operation: OperationFactory) -> Future[Any] | None:
        """Submit one transport coroutine while enforcing serialization.

        Args:
            operation: Factory that receives the loop-owned transport and
                returns the coroutine to execute.

        Returns:
            A thread-safe future for the coroutine, or ``None`` when scheduling
            is not currently allowed.
        """
        with self._state_lock:
            if self._closed:
                return None
            if self._active_future is not None and not self._active_future.done():
                return None
            if self._loop is None or self._transport is None:
                return None

            future = asyncio.run_coroutine_threadsafe(
                operation(self._transport), self._loop
            )
            self._active_future = future
            return future

    def _finish(self, future: Future[Any]) -> bool:
        """Release an operation slot and indicate whether signals may emit.

        Args:
            future: Future whose completion callback is currently running.

        Returns:
            ``True`` while the controller remains open.
        """
        with self._state_lock:
            if self._active_future is future:
                self._active_future = None
            return not self._closed

    def _scan_completed(self, future: Future[Any]) -> None:
        """Translate a completed scan future into success or failure signals."""
        if not self._finish(future):
            return
        try:
            devices = future.result()
        except FutureCancelledError:
            return
        except Exception as error:
            self.scan_failed.emit(self._error_message(error))
            return
        self.scan_finished.emit(devices)

    def _connection_completed(self, address: str, future: Future[Any]) -> None:
        """Record a successful link or publish its connection error.

        Args:
            address: Address supplied to :meth:`connect`.
            future: Completed transport connection future.
        """
        if not self._finish(future):
            return
        try:
            future.result()
        except FutureCancelledError:
            return
        except Exception as error:
            self.connection_failed.emit(address, self._error_message(error))
            return

        with self._state_lock:
            self._connected_address = address
        self.connection_succeeded.emit(address)

    def _disconnection_completed(self, address: str, future: Future[Any]) -> None:
        """Publish the outcome of an explicit disconnection request.

        Args:
            address: Address that was connected when disconnection started.
            future: Completed transport disconnection future.
        """
        if not self._finish(future):
            return
        try:
            future.result()
        except FutureCancelledError:
            return
        except Exception as error:
            self.connection_failed.emit(address, self._error_message(error))
            return
        self._publish_disconnected(address)

    def _transport_disconnected(self, address: str) -> None:
        """Receive Bleak's backend disconnection callback."""
        self._publish_disconnected(address)

    def _publish_disconnected(self, address: str) -> None:
        """Clear matching connection state and emit exactly once.

        Args:
            address: Platform identifier reported by the transport.
        """
        with self._state_lock:
            if self._closed or self._connected_address != address:
                return
            self._connected_address = None
        self.disconnected.emit(address)

    @staticmethod
    def _error_message(error: Exception) -> str:
        """Return a non-empty message suitable for presentation in the UI."""
        return str(error).strip() or error.__class__.__name__
