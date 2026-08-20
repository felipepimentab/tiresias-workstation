# BLE protocol definition

Protocol v1 uses little-endian fixed records. The service UUID is
`7b9a0001-6e4f-4b2d-a9c8-4f2e6f5d1000`; it is the discovery identity, so the
advertised local name is not authoritative. Characteristics use `...0002` to
`...0006` in the first UUID field with the same suffix:

| Characteristic | Access | Value |
| --- | --- | --- |
| Protocol Information (`0002`) | Read | 32-byte compatibility record |
| Catalog (`0003`) | Read/offset | 16-byte header plus 32-byte entries |
| Status (`0004`) | Read, notify | 16-byte coherent state |
| Request (`0005`) | Write | 12-byte GET/SET request |
| Response (`0006`) | Indicate | 16-byte correlated terminal result |

Standard DIS manufacturer, model, serial, hardware revision, and firmware
revision are read independently when present.

## Records

- Protocol Information: `<BBHIHHHHIIII>` — version, length, capabilities,
  request/response limits, catalog shape, layout ID, catalog CRC, boot ID, and
  parameter revision.
- Catalog header: `<BBHHHII>`; entry: `<HBBHBBiiii8s>`. Entries expose stable
  IDs, access flags, Q5.23 bounds/default/step, unit, and name. DSP addresses are
  diagnostic metadata and are never an operation API.
- Request: `<BBIHi>` — opcode, flags, transaction ID, parameter ID, value.
- Response: `<BBIHiI>` — opcode, result, transaction ID, parameter ID, value,
  committed revision.
- Status: `<BBBBIIHH>` — state, flags, last result, revision, last transaction,
  and last parameter.

GET is opcode 1 and SET is opcode 2. Result codes are OK, bad request, not
found, read-only, out of range, busy, persistence failure, and internal error.
The workstation subscribes before writing, permits one request at a time, and
accepts only the matching transaction ID/opcode/parameter response.

SET success means the CRC-protected parameter image was committed to internal
flash. Protocol v1 advertises that actual DSP application is deferred; the UI
states this explicitly and never treats the ATT write response as completion.
