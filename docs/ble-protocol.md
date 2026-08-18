# BLE protocol definition

The custom Tiresias GATT service is not yet defined. The MVP architecture must
not embed temporary UUIDs or packet assumptions outside the protocol adapter.

## Decisions required

- Advertised device name and/or service UUID used for discovery
- Service and characteristic UUIDs
- Readable device-information fields
- Control, parameter-data, status, and notification characteristics
- Supported write modes: with response, without response, or both
- Maximum payload and MTU-dependent chunking
- Parameter-memory addressing and byte order
- Transfer framing, sequence numbers, and completion command
- Integrity checking and board-side validation
- Acknowledgments, errors, timeouts, and retry behavior
- Cancellation and recovery after disconnection
- Protocol and parameter-table version negotiation
- Pairing, bonding, and authorization requirements

## Expected operations

The workstation needs protocol-level operations rather than raw UUID access:

- Read device information
- Begin a parameter transfer
- Write a parameter block
- Complete or abort a transfer
- Read or receive transfer status

The service definition should make a failed or incomplete transfer detectable
and should avoid activating partially written parameters.

