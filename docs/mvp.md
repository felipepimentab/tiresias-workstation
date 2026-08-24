# Minimum viable product

## Goal

Validate the end-to-end architecture by discovering a Tiresias DK, inspecting
its custom service, and remotely reading fixed DSP parameters and persistently
changing the supported scalar controls.

## Required workflow

1. The user opens the application and scans for a Tiresias DK.
2. The user connects to a discovered board.
3. The application reads and displays available device information.
4. The application validates the shared fixed contract and displays its blocks and parameters.
5. The user reads a parameter by stable ID and selects an in-range scalar value where writable.
6. The application reports success only after firmware confirms flash commit.
7. The user can repeat reads and writes without reconnecting.

## Included

- Device discovery, connection, and disconnection
- Connection-state indication
- Custom-service reads and writes
- Basic device-information view
- Shared fixed contract with ID, version, count, and CRC validation
- Stable-ID, indexed-word reads and persistent scalar writes
- Correlated progress and actionable terminal error reporting
- Diagnostic logging useful during board characterization

## Excluded

- Audiogram entry or import
- CAMEQ or pyClarity integration
- NAL-NL2 integration
- Raw-address DSP access
- Atomic multiword LUT writes
- Bundled N1–N7/S1–S3 whole-profile transfer
- Generation of SigmaStudio parameter tables
- Firmware update support
- Clinical fitting or patient-data management

## Acceptance criteria

This architecture-validation MVP is complete when a user can connect to a
supported board, validate the protocol and contract fingerprint, read every exposed
parameter, and persist every writable scalar without restarting either side.
Each word operation must have an unambiguous correlated result, and each write
must have a firmware-confirmed revision.
