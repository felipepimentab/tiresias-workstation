# Product requirements

## Purpose

Tiresias Workstation is the remote BLE workstation for the Tiresias DK. It is
primarily an engineering tool for device testing, characterization, and DSP
configuration.

## Users

- Tiresias DK firmware and hardware developers
- Researchers characterizing the device
- Developers implementing and validating hearing-aid prescriptions

## Functional requirements

The application shall:

- Discover and connect to a Tiresias DK over BLE.
- Expose the board's connection state and useful device information.
- Read and write the board's custom GATT service.
- Select and transfer one of ten bundled DSP parameter tables.
- Report transfer progress, completion, and actionable errors.

Future versions shall support:

- Editing DSP parameters instead of selecting only fixed tables.
- Creating a fitting from an audiogram.
- Using pyClarity's CAMEQ implementation to generate prescriptions and SigmaStudio
  parameter tables.
- Adding other prescription engines, such as a custom NAL-NL2 wrapper.

## Quality requirements

- Support Windows, macOS, and Linux from one Python codebase.
- Keep the UI responsive during BLE and parameter-generation operations.
- Isolate the UI, BLE transport, board protocol, and prescription engines.
- Prevent concurrent or partial parameter transfers where possible.
- Make protocol and transformation logic testable without BLE hardware.
- Record enough diagnostic context to investigate connection and transfer failures.

## Product boundary

The first releases are engineering and characterization tools. They are not a
clinical fitting system and shall not imply that a selected prescription has
been clinically validated for an individual user.

