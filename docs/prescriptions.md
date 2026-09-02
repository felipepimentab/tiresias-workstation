# Prescriptions and parameter tables

## MVP catalog

The MVP contains ten precomputed SigmaStudio parameter tables corresponding to
the standard audiograms described by Bisgaard, Vlaming, and Dahlquist (2010):

- N1–N7: flat or moderately sloping hearing losses
- S1–S3: steeply sloping hearing losses

Strictly, Bisgaard et al. define standard **audiograms**, not prescription
algorithms. In this project, “the ten standard prescriptions” is shorthand for
the ten existing prescription results and byte tables associated with those
audiograms.

All ten prescriptions are bundled in the workstation as immutable Python
assets whose opaque bytes are mapped to the fixed DSP parameter IDs. Each
bundled prescription carries:

- Stable profile identifier
- Display name and short description
- Parameter-table format and version
- Payload length
- Integrity hash or checksum
- Provenance or source revision

Each integrity digest covers every stable parameter ID, its payload length,
and its payload bytes. This catches both byte corruption and accidental
remapping of a value to the wrong DSP parameter.

The application must validate assets before writing them to a board. It should
not depend on the external repository being present at runtime.

## Loading pipeline

The supported format is `SigmaDSP 5.23 big-endian parameter words`, version 1.
A prescription supplies metadata plus an ordered tuple of stable DSP parameter
IDs and opaque byte arrays. `PrescriptionLoader` accepts this domain model from
any catalog or future fitting engine; it is not coupled to the bundled assets.

Before the first write, the loader validates the format version and checks that
every parameter exists on the connected board, has the expected byte count, and
is writable. It then persists parameters sequentially and reports confirmed
parameter and byte progress. Firmware currently commits each four-byte LUT
chunk independently. If a transfer fails, the active parameter may therefore
be partial; the reported error instructs the user to retry the complete
prescription.

The current firmware advertises deferred DSP application. A successful load
means all prescription bytes were confirmed and persisted on the board; live
codec programming remains a separate firmware milestone.

## Generated custom prescriptions

The workstation accepts a two-ear audiogram and asks a selectable prescription
rule to produce a full target before a separate adapter maps one ear to
SigmaDSP parameter values:

```text
Audiogram -> prescription rule -> prescription target -> DSP mapping -> parameter bytes
```

The first rule is the compressive CEC1 CAMFIT implementation from pyClarity.
The full audiogram, target curves, calibrated mapping, and final parameter
bytes are saved together as versioned JSON. See
[Audiogram fitting and local prescriptions](audiogram-fitting.md) for the data
formats, persistence behavior, and extension points.

## Reference

Bisgaard, N., Vlaming, M. S. M. G., & Dahlquist, M. (2010). “Standard
Audiograms for the IEC 60118-15 Measurement Procedure.” *Trends in
Amplification*, 14(2), 113–120.
[doi:10.1177/1084713810379609](https://doi.org/10.1177/1084713810379609)
