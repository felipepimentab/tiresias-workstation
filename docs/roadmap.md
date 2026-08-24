# Roadmap

## Phase 0 — Foundation

- PySide6 Qt Widgets application
- Bleak dependency
- uv-managed environment and lockfile
- Initial project documentation

## Phase 1 — BLE feasibility and protocol

- Define the custom Tiresias GATT service
- Prove discovery, connection, read, write, notification, and reconnection
- Exercise Windows, macOS, and Linux behavior
- Capture protocol decisions in `ble-protocol.md`

## Phase 2 — Device workstation

- Add device discovery and connection UI
- Display device and protocol information
- Add connection-state and diagnostic reporting
- Implement safe parameter transfer and failure recovery

## Phase 3 — MVP prescription catalog

- Import the ten existing parameter tables
- Record and validate asset metadata
- Add N1–N7 and S1–S3 selection UI
- Transfer each table and report progress and result
- Verify repeated cycling during DK characterization

## Phase 4 — MVP release

- Add automated tests using fake BLE and protocol adapters
- Perform manual hardware validation on supported platforms
- Package and sign platform-native application artifacts
- Document installation, troubleshooting, and release procedure

## Post-MVP

1. Generate the shared DSP contract from the SigmaStudio `.params` export
2. Optionally negotiate a device-provided dynamic catalog if product direction requires it
3. Flexible DSP parameter inspection and editing
4. Audiogram input and validation
5. pyClarity/CAMEQ prescription generation
6. Automatic SigmaStudio parameter-table generation
7. Pluggable prescription engines, including a custom NAL-NL2 adapter
8. Comparison and characterization tools for prescriptions and board responses
