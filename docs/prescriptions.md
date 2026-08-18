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

The tables already exist in another repository. Their import mechanism is
still to be selected. Whichever mechanism is chosen, each bundled asset should
carry:

- Stable profile identifier
- Display name and short description
- Parameter-table format and version
- Payload length
- Integrity hash or checksum
- Provenance or source revision

The application must validate assets before writing them to a board. It should
not depend on the external repository being present at runtime.

## Future generation

A future workflow will accept an audiogram and ask a prescription engine to
produce a fitting and SigmaStudio parameter table:

```text
Audiogram -> prescription engine -> DSP model -> parameter bytes
```

The first planned engine is an adapter around pyClarity's CAMEQ
implementation. Other engines, including a custom NAL-NL2 wrapper, should
implement the same application-facing interface.

## Reference

Bisgaard, N., Vlaming, M. S. M. G., & Dahlquist, M. (2010). “Standard
Audiograms for the IEC 60118-15 Measurement Procedure.” *Trends in
Amplification*, 14(2), 113–120.
[doi:10.1177/1084713810379609](https://doi.org/10.1177/1084713810379609)

