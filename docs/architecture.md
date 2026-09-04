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
+----------------------+-----------------------+----------------------------+
| Tiresias BLE adapter | Prescription catalogs | Fitting + mapping adapters |
| Bleak + board GATT    | Bundled + local JSON  | pyClarity + SigmaDSP        |
+----------------------+-----------------------+----------------------------+
```

## Modules

### Presentation

Windows, dialogs, device lists, status indicators, and profile controls. The UI
emits user intent and renders application state; it does not construct BLE
packets or generate DSP parameters.

### Application

Coordinates complete operations such as scan, connect, read device information,
and apply a prescription. `PrescriptionLoader` preflights the complete format
and connected-device contract before serializing parameter writes. The Qt
controller owns scheduling and publishes progress, completion, and errors.

### Domain

Defines stable models and interfaces for devices, connection state,
prescriptions, parameter tables, and transfers. It has no dependency on Qt,
Bleak, pyClarity, or a particular board protocol.

### Adapters

- **Bleak transport:** scanning, connections, GATT reads/writes, and notifications.
- **Tiresias protocol:** UUIDs, fixed record decoding, contract compatibility,
  transaction correlation, and firmware result translation.
- **DSP contract:** fixed block and parameter names, IDs, word counts, and flags.
- **Prescription catalogs:** validate the ten immutable MVP tables and locally
  generated JSON artifacts behind one catalog interface.
- **Fitting rules:** adapt pyClarity CAMFIT or future rules such as NAL-NL2 to
  a common, hardware-independent `PrescriptionTarget`.
- **DSP mapping:** converts a selected target ear through a versioned detector
  calibration into the fixed SigmaDSP parameter contract.

## Main extension points

- `TiresiasClient`: ready-session and stable-ID parameter operations.
- `PrescriptionCatalog`: available named, precomputed parameter tables.
- `PrescriptionLoader`: applies any validated prescription independently of its
  catalog or generation source.
- `PrescriptionRule`: generates a full two-ear target from an audiogram.
- `DspPrescriptionMapper`: converts a target to board-specific parameter values.
- `GeneratedPrescriptionStore`: persists every inspectable generation stage.

The UI applies a `Prescription` without knowing whether it came from a bundled
asset, pyClarity, or another prescription engine. The same loader therefore
supports generated custom prescriptions that use the supported format and fixed
parameter contract.

For the architecture-validation MVP, `BleakDeviceTransport` owns generic BLE
and GATT mechanics while `TiresiasProtocolClient` owns the board protocol. The
Qt controller serializes use cases on its worker loop; screens receive only
domain snapshots and terminal results.

## Dependency rule

Dependencies point inward: adapters depend on domain interfaces, never the
reverse. This keeps BLE hardware and external libraries replaceable in tests
and future releases.
