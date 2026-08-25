# BLE protocol definition

Protocol v4 uses fixed records with little-endian integer metadata and opaque
parameter bytes. The service UUID is
`7b9a0001-6e4f-4b2d-a9c8-4f2e6f5d1000`; it is the discovery identity, so the
advertised local name is not authoritative. Characteristics use the following
first UUID fields with the same suffix; `...0003` is reserved from protocol v1:

| Characteristic | Access | Value |
| --- | --- | --- |
| Protocol Information (`0002`) | Read | 24-byte protocol and contract record |
| Status (`0004`) | Read, notify | 16-byte coherent state |
| Request (`0005`) | Write | 12-byte byte-offset GET/SET request |
| Response (`0006`) | Indicate | 16-byte byte-chunk terminal result |

Standard DIS manufacturer, model, serial, hardware revision, and firmware
revision are read independently when present.

## Records

- Protocol Information: `<BBHIHHIII>` — version, length, capabilities,
  request/response limits, contract CRC, boot ID, and parameter revision.
- Request: `<BBIBB4s>` — opcode, flags, transaction ID, byte parameter ID, byte
  offset, and four opaque parameter bytes.
- Response: `<BBIBB4sI>` — opcode, result, transaction ID, parameter ID, byte
  offset, four opaque parameter bytes, and committed revision.
- Status: `<BBBBIIBBH>` — state, flags, last result, revision, last transaction,
  last parameter ID, and last byte offset.

GET is opcode 1 and SET is opcode 2. Result codes are OK, bad request, not
found, read-only, out of range, busy, persistence failure, internal error, and
DSP access failure.
The workstation subscribes before writing, permits one request at a time, and
accepts only the matching transaction ID/opcode/parameter/offset response.

## Fixed DSP contract

The workstation and firmware compile the same 15-entry contract. Protocol
Information carries only its CRC32 fingerprint; a
mismatch means the two hard-coded catalogs differ. Human-readable block and
parameter names live only in the workstation. DSP addresses live only in
firmware and never cross BLE.

All parameters are opaque byte arrays. The contract gives each parameter a
stable ID, block ID, byte count, and access flags, without assigning numerical
meaning or byte order. Its CRC32 is currently `0x22045c5c`. Each compressor LUT
contains 136 bytes and the Soft Clip LUT contains 180 bytes. The workstation
reads parameters sequentially in four-byte chunks and requires one stable
revision across the assembled byte array. LUT writes remain unsupported.

Firmware currently advertises deferred DSP access while its Codec Adapter
parameter operations remain hardware-validation stubs. All reads use the
firmware's complete synchronized RAM mirror, including LUT bytes. Bluetooth-only
builds compile out codec calls and persist SET operations to flash and RAM.
ADAU1787 builds require codec success before saving flash or advancing RAM, so
SET reports DSP failure while the codec write stub returns unsupported. The UI
never treats the ATT write response as operation completion; only the correlated
indication confirms success.
