# BLE protocol definition

Protocol v2 uses little-endian fixed records. The service UUID is
`7b9a0001-6e4f-4b2d-a9c8-4f2e6f5d1000`; it is the discovery identity, so the
advertised local name is not authoritative. Characteristics use the following
first UUID fields with the same suffix; `...0003` is reserved from protocol v1:

| Characteristic | Access | Value |
| --- | --- | --- |
| Protocol Information (`0002`) | Read | 32-byte compatibility record |
| Status (`0004`) | Read, notify | 16-byte coherent state |
| Request (`0005`) | Write | 12-byte indexed-word GET/SET request |
| Response (`0006`) | Indicate | 16-byte indexed-word terminal result |

Standard DIS manufacturer, model, serial, hardware revision, and firmware
revision are read independently when present.

## Records

- Protocol Information: `<BBHIHHHHIIII>` — version, length, capabilities,
  request/response limits, contract version/count/ID/CRC, boot ID, and parameter
  revision.
- Request: `<BBIBBi>` — opcode, flags, transaction ID, byte parameter ID, byte
  word index, and value.
- Response: `<BBIBBiI>` — opcode, result, transaction ID, parameter ID, word
  index, value, and committed revision.
- Status: `<BBBBIIBBH>` — state, flags, last result, revision, last transaction,
  last parameter ID, and last word index.

GET is opcode 1 and SET is opcode 2. Result codes are OK, bad request, not
found, read-only, out of range, busy, persistence failure, internal error, and
DSP access failure.
The workstation subscribes before writing, permits one request at a time, and
accepts only the matching transaction ID/opcode/parameter/word response.

## Fixed DSP contract

The workstation and firmware compile the same 15-entry contract. Protocol
Information must report contract ID `0x54525001`, version `1`, and CRC32
`0xf62c1808`; otherwise the workstation rejects the session. Human-readable
block and parameter names live only in the workstation. DSP addresses live
only in firmware and never cross BLE.

All parameters are readable Q5.23 values by default. Flags opt six scalar
parameters into writes and mark ADC Select and Source Select as integers. Each
compressor LUT has 34 words and the Soft Clip LUT has 45. The workstation reads
multiword parameters sequentially by word index and requires one stable
revision across the assembled value. LUT writes are intentionally unsupported.

Firmware currently advertises deferred DSP access while its Codec Adapter
parameter operations remain hardware-validation stubs. Scalar reads use the
persistent cache, LUT reads report DSP access failure, and scalar SET commits the
CRC-protected record without applying hardware. The UI never treats the ATT
write response as operation completion; only the correlated indication confirms
success.
