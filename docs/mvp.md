# Minimum viable product

## Goal

Enable repeatable testing of the Tiresias DK by applying ten existing DSP
parameter tables over BLE.

## Required workflow

1. The user opens the application and scans for a Tiresias DK.
2. The user connects to a discovered board.
3. The application reads and displays available device information.
4. The user selects one of the ten standard profiles: N1–N7 or S1–S3.
5. The application writes the corresponding parameter table through the custom
   BLE service.
6. The application reports whether the transfer completed or failed.
7. The user can select another profile and repeat the transfer.

## Included

- Device discovery, connection, and disconnection
- Connection-state indication
- Custom-service reads and writes
- Basic device-information view
- Fixed catalog of ten precomputed parameter tables
- Profile selection and application
- Transfer progress and error reporting
- Diagnostic logging useful during board characterization

## Excluded

- Audiogram entry or import
- CAMEQ or pyClarity integration
- NAL-NL2 integration
- Arbitrary DSP parameter editing
- Generation of SigmaStudio parameter tables
- Firmware update support
- Clinical fitting or patient-data management

## Acceptance criteria

The MVP is complete when a user can connect to a supported board, identify it,
and repeatedly cycle through all ten bundled tables without restarting the
application. Each transfer must have an unambiguous success or failure result.

