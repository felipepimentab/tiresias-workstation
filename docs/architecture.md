# Application architecture

## Direction

The application is one Python desktop process. PySide6 provides the Qt Widgets
UI, and Bleak adapts the operating system's native BLE stack.

```text
Qt Widgets UI
      |
Application use cases
      |
Domain interfaces
      |
+----------------------+----------------------+-------------------+
| Tiresias BLE adapter | Prescription catalog | Fitting engines   |
| Bleak + board GATT    | Bundled byte tables  | Future adapters   |
+----------------------+----------------------+-------------------+
```

## Modules

### Presentation

Windows, dialogs, device lists, status indicators, and profile controls. The UI
emits user intent and renders application state; it does not construct BLE
packets or generate DSP parameters.

### Application

Coordinates complete operations such as scan, connect, read device information,
and apply a prescription. It owns progress, cancellation, and error reporting.

### Domain

Defines stable models and interfaces for devices, connection state,
prescriptions, parameter tables, and transfers. It has no dependency on Qt,
Bleak, pyClarity, or a particular board protocol.

### Adapters

- **Bleak transport:** scanning, connections, GATT reads/writes, and notifications.
- **Tiresias protocol:** UUIDs, fixed record decoding, contract compatibility,
  transaction correlation, and firmware result translation.
- **DSP contract:** fixed block and parameter names, IDs, word counts, and flags.
- **Bundled prescription catalog:** loads and validates the ten MVP parameter tables.
- **Future fitting engines:** adapt pyClarity/CAMEQ, NAL-NL2, or other rules to a
  common prescription interface.

## Main extension points

- `TiresiasClient`: ready-session and stable-ID parameter operations.
- `PrescriptionCatalog`: available named, precomputed parameter tables.
- `PrescriptionEngine`: generates a parameter table from fitting inputs.

The UI applies a parameter table without knowing whether it came from a bundled
asset, pyClarity, or another prescription engine.

For the architecture-validation MVP, `BleakDeviceTransport` owns generic BLE
and GATT mechanics while `TiresiasProtocolClient` owns the board protocol. The
Qt controller serializes use cases on its worker loop; screens receive only
domain snapshots and terminal results.

## Dependency rule

Dependencies point inward: adapters depend on domain interfaces, never the
reverse. This keeps BLE hardware and external libraries replaceable in tests
and future releases.
