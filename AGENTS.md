# AGENTS.md

## Project

Tiresias Workstation is a cross-platform Python desktop application for
discovering, connecting to, and configuring the Tiresias DK over Bluetooth Low
Energy. PySide6 provides the Qt Widgets interface and Bleak provides access to
the operating system's native BLE stack.

## Documentation standard

Use Google-style docstrings consistently throughout the Python codebase.

- Give every Python module a docstring that explains its responsibility and
  architectural boundary.
- Document public classes, protocols, functions, methods, and application entry
  points.
- Document private methods when they coordinate asynchronous work, thread
  synchronization, lifecycle transitions, resource ownership, data
  normalization, or other behavior that is not immediately obvious.
- Use the standard Google-style sections where applicable:
  `Args:`, `Returns:`, `Raises:`, and `Attributes:`.
- For Qt objects, include a `Signals:` section on classes that expose signals.
  State each signal's payload types and when it is emitted.
- Describe units and platform-dependent values explicitly. For example, RSSI is
  measured in dBm, timeouts are measured in seconds, and a BLE identifier may be
  a MAC address or UUID depending on the operating system.
- Document callback frequency and ownership assumptions, including whether a
  callback may run repeatedly or from a background thread.
- Keep documentation synchronized with behavior whenever code changes.

Example:

```python
def connect(self, address: str, *, timeout: float) -> bool:
    """Request a connection to a discovered BLE device.

    Args:
        address: Platform identifier reported by the latest scan.
        timeout: Maximum connection duration in seconds.

    Returns:
        ``True`` if the operation was scheduled, otherwise ``False``.

    Raises:
        ValueError: If the address was not present in the latest scan.
    """
```

## Commenting guidelines

- Add inline comments for intent, constraints, race prevention, cleanup order,
  platform quirks, and non-obvious design decisions.
- Explain why a concurrency or lifecycle step is necessary, not merely what the
  following statement does.
- Do not narrate straightforward assignments, conditions, widget construction,
  or code already made clear by names and docstrings.
- Prefer updating unclear names or structure over compensating with excessive
  comments.
- Do not leave commented-out code, speculative notes, or stale implementation
  history in source files.

## Architecture and implementation

- Keep Qt presentation, application coordination, domain types, and Bleak
  transport concerns separated.
- Keep the UI responsive. BLE and other blocking or asynchronous work must not
  run on the Qt UI thread.
- Keep domain models independent of PySide6, Bleak, and platform-specific types.
- Preserve existing public APIs unless a requested change requires modifying
  them.
- Keep changes scoped and do not revert unrelated worktree changes.

## Verification

Use fake transports and the offscreen Qt backend for automated checks. Do not
require a physical BLE device or access the machine's Bluetooth adapter during
tests.

Relevant checks:

```sh
.venv/bin/python -m compileall -q src tests
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Do not perform manual Bluetooth scans, physical connection attempts, or hardware
tests unless the developer explicitly requests them.
