# Minimum viable product

## Goal

Validate the end-to-end architecture by discovering a Tiresias DK, inspecting
its custom service, and remotely reading and persistently changing cataloged
DSP parameters.

## Required workflow

1. The user opens the application and scans for a Tiresias DK.
2. The user connects to a discovered board.
3. The application reads and displays available device information.
4. The application validates and displays the firmware-owned parameter catalog.
5. The user reads a parameter by stable ID and selects an in-range Q5.23 value.
6. The application reports success only after firmware confirms flash commit.
7. The user can repeat reads and writes without reconnecting.

## Included

- Device discovery, connection, and disconnection
- Connection-state indication
- Custom-service reads and writes
- Basic device-information view
- Firmware-owned parameter catalog with integrity and layout validation
- Stable-ID parameter reads and persistent writes
- Correlated progress and actionable terminal error reporting
- Diagnostic logging useful during board characterization

## Excluded

- Audiogram entry or import
- CAMEQ or pyClarity integration
- NAL-NL2 integration
- Raw-address DSP access
- Applying the persisted value to the physical DSP (placeholder in firmware)
- Bundled N1–N7/S1–S3 whole-profile transfer
- Generation of SigmaStudio parameter tables
- Firmware update support
- Clinical fitting or patient-data management

## Acceptance criteria

This architecture-validation MVP is complete when a user can connect to a
supported board, validate its protocol/catalog, and repeatedly read and persist
every exposed parameter without restarting either side. Each write must have an
unambiguous correlated result and a firmware-confirmed revision.
