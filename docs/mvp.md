# Minimum viable product

## Goal

Validate the end-to-end architecture by discovering a Tiresias DK, inspecting
its custom service, and remotely reading fixed DSP parameters and persistently
changing supported opaque parameter byte arrays.

## Required workflow

1. The user opens the application and scans for a Tiresias DK.
2. The user connects to a discovered board.
3. The application reads and displays available device information.
4. The application validates the shared fixed contract and displays its blocks and parameters.
5. The user reads a parameter by stable ID and supplies a complete byte array where writable.
6. The application reports success only after firmware confirms flash commit.
7. The user selects a bundled prescription and loads its complete parameter set.
8. The user can repeat reads, writes, and prescription loads without reconnecting.

## Included

- Device discovery, connection, and disconnection
- Connection-state indication
- Custom-service reads and writes
- Basic device-information view
- Shared fixed contract with ID, version, count, and CRC validation
- Stable-ID, byte-offset reads and persistent opaque-byte writes
- N1–N7/S1–S3 catalog selection and whole-profile persistence
- Format and device-contract preflight before prescription transfer
- Correlated progress and actionable terminal error reporting
- Diagnostic logging useful during board characterization

## Excluded

- Audiogram entry or import
- CAMEQ or pyClarity integration
- NAL-NL2 integration
- Raw-address DSP access
- Atomic multi-chunk LUT writes
- Generation of SigmaStudio parameter tables
- Firmware update support
- Clinical fitting or patient-data management

## Acceptance criteria

This architecture-validation MVP is complete when a user can connect to a
supported board, validate the protocol and contract fingerprint, read every exposed
parameter, persist every writable byte array, and load every bundled prescription
without restarting either side. Each byte-chunk operation must have an
unambiguous correlated result, and each write must have a firmware-confirmed
revision.
