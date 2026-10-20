# BLE protocol definition

Protocol v6 transfers one complete parameter per operation and adds separate
system-status and system-command services. It is incompatible with v5; update
firmware and workstation together. The parameter-service UUID remains
`7b9a0001-6e4f-4b2d-a9c8-4f2e6f5d1000`. Discovery uses this UUID, not the local
name. Characteristic UUIDs use the same suffix; `0003` remains reserved.

| Characteristic | Access | Value |
| --- | --- | --- |
| Protocol Information (`0002`) | Read | 24 bytes |
| Status (`0004`) | Read, notify | 16 bytes |
| Request (`0005`) | Write with response | 8-byte header, then 0–180 bytes |
| Response (`0006`) | Indicate | 12-byte header, then 0–180 bytes |

Standard DIS identity fields remain optional and are read independently.
Metadata integers are little-endian; parameter bytes have no transport-level
numeric interpretation or byte order. Headers are explicitly encoded, never
native C structures.

## Wire records

- Protocol Information: `<BBHIHHIII>` — major (6), minor (0), record size (24),
  capabilities, maximum request size (188), maximum response size (192), contract
  CRC32, boot ID, parameter revision.
- Request header: `<BBIBB>` — opcode, flags (zero), nonzero transaction ID,
  parameter ID, payload byte count. Payload immediately follows the header.
- Response header: `<BBIBBI>` — opcode, result, transaction ID, parameter ID,
  payload byte count, committed revision. Payload immediately follows the header.
- Status: `<BBBBIIBBH>` — control state, flags, last result, reserved zero,
  revision, last transaction ID, last parameter ID, reserved zero, reserved zero.
  Byte 13, formerly the chunk offset, remains reserved.

GET (opcode 1) has no request payload and returns the entire parameter snapshot.
SET (opcode 2) must carry exactly the contract byte count and returns the entire
confirmed value. A failed operation returns only the response header, with a
zero payload count. Result codes retain their v4 values: OK, bad request, not
found, read-only, out of range, busy, persistence failure, internal error, DSP
failure. Admission failures are ATT errors, not application results.

The 15-entry contract CRC32 is `0x0056062d`. ID 2 (source selection) is read-only;
source changes use the system-command service. IDs 3–10 each contain a writable
136-byte compressor LUT; ID 15 is a writable 180-byte soft clip LUT. The updated
access flag enables complete output-stage loading and requires matching firmware
and workstation catalogs. Names live in the workstation and DSP addresses remain in firmware.

## MTU and framing

A request and its successful response must each fit a single ordinary ATT
operation. Required ATT MTU is `12 + parameter_byte_count + 3`: 19 for a four-byte
value (the default MTU of 23 suffices), 151 for a compressor LUT, and 195 for the
largest GET. Firmware is configured with a local L2CAP TX MTU of 498; the actual
negotiated peer MTU still determines admission. MTU negotiation is handled by
the BLE stack/central; the client does not split parameters to accommodate a
smaller MTU. A peer must negotiate at least 195 to use the whole catalog.

Firmware rejects insufficient MTU before queueing or changing any value. It
also rejects incomplete/oversized SETs, mismatched payload counts, nonzero
attribute offsets, write commands, and ATT prepare/execute writes. Long-write
fragments are deliberately not accumulated or applied. A central that attempts
a long write on a small-MTU connection receives an ATT error without a commit.
This avoids backend-dependent long-write assembly semantics.

The workstation uses Bleak's explicit `response=True` write API. Its API accepts
write-with-response values up to 512 bytes, but that API limit does not establish
the negotiated MTU or server support for long writes.
See [Bleak write documentation](https://bleak.readthedocs.io/en/latest/api/client.html#bleak.BleakClient.write_gatt_char).

## Atomicity and failure behavior

The service copies the complete accepted request into a fixed single-entry
queue. Its worker calls `codec_parameters_set()` exactly once, without merging
any old bytes. In a hardware-enabled build, that function first applies and
reads back the codec value, then saves the complete value under its parameter's
Settings key, updates the RAM mirror, and advances the revision once. Identical
values are successful no-ops.
GET returns bytes and revision from one mutex-protected snapshot.

- Malformed or incomplete requests change nothing.
- Disconnect before a queued request is processed discards the request.
- Disconnect after processing starts may still permit a complete commit.
- A persistence failure leaves the old RAM mirror and revision intact.
- A lost indication after commit makes the outcome uncertain, not partial.
  Reconnect and read the complete parameter before deciding whether to retry.
- Each request requires a Response subscription, an authorized READY connection,
  and the sole request slot. Firmware retains indication storage until the stack
  releases it. Busy admission is an ATT insufficient-resources error.

The workstation requires matching transaction ID, opcode, parameter ID, exact
value length, and (for SET) exact echoed bytes. ATT write acknowledgment alone
never means successful persistence. The exchange has a deadline and no automatic
SET retries. Status is a snapshot, not a durable transaction log.

These guarantees cover communication-induced partial updates of each stored
parameter. Physical flash fault/power-loss behavior remains that of the Settings
NVS backend and has not been hardware-tested here. The ADAU1787 path applies
hardware before persistence: a persistence failure following DSP application
is not a transactional hardware guarantee. Compile-only verification does not
establish physical DSP or flash-fault behavior.

## System status and commands

The status service uses UUID `7b9a0021-6e4f-4b2d-a9c8-4f2e6f5d1000` with a
read/notify characteristic `7b9a0022-6e4f-4b2d-a9c8-4f2e6f5d1000`. Its
eight-byte snapshot is `[version=1, device, control, audio, codec, 0, 0, 0]`.
The four state bytes mirror the latest Device Controller, Control Link, Audio
Streaming, and Codec Controller Zbus states. Read gives a snapshot; notifications
report changes while the control connection is ready. These are state values,
not measurements, command results, or a durable event history.

The command service uses UUID `7b9a0011-6e4f-4b2d-a9c8-4f2e6f5d1000` with a
write-with-response characteristic `7b9a0012-6e4f-4b2d-a9c8-4f2e6f5d1000`.
Each write contains one opcode: 1 starts broadcast discovery, 2 stops it, 3
selects local audio, 4 requests broadcast audio, and 5 requests recoverable idle.
The BLE handler publishes the corresponding Device Controller command; it does
not call subsystem operations directly. A successful ATT write means the request
was admitted, not that the target state was reached. Observe the reported
states to confirm the outcome. The sleep request disconnects the control link;
a button press wakes the board and restores connectable control advertising.

Under the default profile, broadcast discovery is off at startup and is enabled
by command. The explicit P1 power-evaluation profile starts it automatically.
The source selector remains readable in the parameter catalog but cannot be set
through the parameter service. A codec source change is instead requested as a
system command, allowing the Codec Controller to enforce its existing stream
availability and fallback policy.

## Prescriptions

The current prescription loader makes 11 atomic parameter SETs (eight LUTs and
three gains, 1,100 bytes). It does not commit the prescription atomically. A
failure can leave earlier complete parameters from the new prescription and
later complete parameters from the old one. Retrying the whole prescription is
idempotent for unchanged values, but requires restored communication.

The firmware document `docs/architecture/prescription-transactions.md` evaluates
an explicit begin/stage/commit protocol and durable A/B prescription records.
That design is proposed, not implemented by v6.
