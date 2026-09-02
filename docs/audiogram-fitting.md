# Audiogram fitting and local prescriptions

## End-to-end flow

The Audiogram fitting page implements the same CAMFIT prescription path used
to create the validated assets in `tiresias-eval`, while keeping every
transformation explicit:

```text
two-ear audiogram
        |
        v
selectable prescription rule (CAMFIT through pyClarity)
        |
        v
full prescription target (2 ears x 9 bands x 121 levels)
        |
        v
select one ear + measured ADAU1787 detector calibration
        |
        v
DSP mapping (8 bands x 34 detector knots + shared bias)
        |
        v
11 fixed-contract parameter values (1,100 bytes)
```

The current board signal path is monaural. The rule always preserves distinct
left- and right-ear targets, but the user must select which ear becomes the
eight compressor LUTs loaded into the board. This choice is stored in the DSP
mapping. It does not discard the other ear from the saved artifact.

The feature is an engineering and characterization workflow, not a clinical
fitting system.

## Stage 1: audiogram

`domain.fittings.Audiogram` is the rule-independent input model:

```json
{
  "frequencies_hz": [250.0, 375.0, 500.0, 750.0, 1000.0],
  "left_levels_db_hl": [10.0, 10.0, 10.0, 10.0, 10.0],
  "right_levels_db_hl": [10.0, 10.0, 10.0, 10.0, 10.0]
}
```

Frequencies are strictly increasing and positive. Both threshold arrays must
have the same length as the frequency array, contain finite values, and remain
within -20 to 140 dB HL. The UI initially provides the ten Bisgaard frequencies
used by the evaluation repository: 250, 375, 500, 750, 1000, 1500, 2000, 3000,
4000, and 6000 Hz.

## Stage 2: prescription target

`PrescriptionRule` is a domain protocol. A rule receives one `Audiogram` and
returns a `PrescriptionTarget`; it does not know about JSON, Qt, BLE, or the
board parameter contract. `PrescriptionWorkbench` indexes implementations by
stable `rule_id`, which allows another rule to be registered without changing
the remaining pipeline.

The first adapter is `PyClarityCamfitRule`. It calls `get_gaintable` from the
pinned pyClarity commit
`9df6486fb0bddc7619b3b99f1b3a5c72c109a3ec`, exactly like
`tiresias-eval/experiments/prescriptions/scripts/generate_camfit_prescriptions.py`.
Use `uv sync` to install the locked runtime. The uv dependency-metadata override
keeps just the fitting dependencies: pyClarity, NumPy, and SciPy. A plain pip
installation does not honor that override and may install pyClarity's full
challenge/ML dependencies.

The adapter uses the evaluation recipe: noise-gate levels
`[38, 38, 36, 37, 32, 26, 23, 22, 8]` dB SPL, noise-gate slope 0,
compression-reference level 0, and maximum output level 100 dB SPL. Audiograms
are resampled by pyClarity in log frequency with constant endpoint extension.
The corrected `sGt` matrix is split from 18 rows into two ears of nine bands,
and gains are rounded to six decimal places exactly as in the evaluation JSON.

The CAMFIT target contains:

- the exact input audiogram for both ears;
- rule ID, display name, source, and pinned revision;
- nine CEC1 band centres and ten edges;
- 121 acoustic input levels from -10 to 110 dB SPL;
- one gain in dB for every ear, band, and input level;
- the fixed 20 ms attack, 100 ms release, and 100 ms RMS time constant;
- the pyClarity constant-extension endpoint policy.

The ninth band is forced to 0 dB, matching the CEC1 boundary path. The full
curves, including negative high-level limiting gains, remain authoritative.
The 45/65/85 dB gains shown in the UI are only a compact preview.
An all-zero ear follows pyClarity's explicit unity-gain special case: it does
**not** retain the 100 dB SPL limiter. Neither this target ceiling nor the
engineering calibration is a guarantee of safe acoustic output from a device.

## Stage 3: DSP mapping

`SigmaDspMapper` is separate from the prescription rule. It maps the selected
ear to the current physical DSP design using the completed
`ADAU1787_EVAL_Tiresias_2026` detector calibration from `tiresias-eval`.
This is the EVAL-board calibration, not an independently measured calibration
of the Tiresias DK. Targets with different first-eight band centres are
rejected; a new rule must supply this filterbank or use an explicit resampling
adapter before this mapper.

For each of the eight active bands it:

1. maps the ADAU1787's 34 detector knots (-90 to +6 dBFS, with the duplicated
   underflow knot) to equivalent acoustic input levels;
2. samples the rule target on that measured mapping;
3. fits the coarse 3 dB LUT in linear gain at 45, 55, 65, 75, 85, and 95 dB SPL;
4. moves gain above the 21 dB LUT allowance into the three shared
   phase-compensation gain stages;
5. quantizes all LUT and bias gains as positive, big-endian SigmaDSP 5.23
   parameter words.

`DspMapping` retains the detector axis, mapped acoustic levels, desired gains,
post-bias LUT gains, recovered quantized gains, total bias, and quantized bias
per stage. These values make differences between a rule target and actual DSP
values inspectable without decoding opaque bytes.

As a regression proof, generating each of the ten Bisgaard audiograms and
mapping its left ear produces the exact eight LUTs, three bias words, and
canonical SHA-256 of the corresponding bundled prescription.

## Stage 4: board parameter values

The final `Prescription` uses the existing loader format:

```text
parameters 3..10   eight 136-byte compressor LUTs
parameters 11..13  three 4-byte phase-compensation gains
total              11 parameters / 1,100 bytes
```

Each parameter is addressed by stable `DspParameterId`. The canonical SHA-256
binds each ID, payload length, and byte array in transfer order. Saving locally
does not write a board; the existing connected-device prescription loader still
preflights and persists the values.
Other parameters, including headroom, compressor timing, and the DSP program,
are not changed by this prescription. The timing metadata records recipe
assumptions rather than additional writes. Calibration/headroom compatibility
must be established separately before acoustic use.

## Local storage and export

Saving creates one versioned JSON file under the platform's Qt application-data
directory in `generated-prescriptions/`. Each custom prescription receives an
opaque `custom-<uuid>` identifier, so duplicate display names are safe. Writes
use a temporary file and atomic replacement.
The application name is `Tiresias Workstation`: typical locations are
`~/Library/Application Support/Tiresias Workstation/` on macOS,
`~/.local/share/Tiresias Workstation/` on Linux (subject to `XDG_DATA_HOME`),
and the Qt application-data location under `%APPDATA%` on Windows. All have
the `generated-prescriptions/` subdirectory. Files are local, unencrypted,
and are not uploaded; treat audiograms and exports as potentially sensitive.

The saved/exported envelope has four inspectable data sections:

```json
{
  "format": "tiresias-generated-prescription",
  "version": 1,
  "audiogram": {},
  "prescription_target": {},
  "dsp_mapping": {},
  "dsp_parameters": {}
}
```

`dsp_parameters.parameters[].data_hex` is the actual byte representation sent
to the board. Loading a stored artifact reconstructs the domain models and
revalidates the DSP contract sizes and canonical digest.

The Audiogram fitting page can:

- generate and preview a target without saving it;
- save it under a custom name;
- list and inspect saved artifacts;
- export the current or a saved artifact as portable JSON;
- delete a selected local artifact after confirmation.

The Prescriptions page combines the immutable bundled catalog and the mutable
local catalog. Deleting a local artifact removes it from that loading catalog;
bundled profiles cannot be deleted.
Deletion permanently removes the managed JSON file, not copies previously
exported elsewhere. Invalid local files are logged and excluded from the list;
the application does not silently rewrite them. There is no JSON-import UI yet.

## Reuse and individual stage inspection

The domain models are frozen dataclasses with explicit units and immutable
tuples. JSON uses arrays for numeric vectors/matrices and hexadecimal strings
for bytes; this avoids Python-specific pickle or ambiguous binary arrays.
Matrix orientation is always `[band][input level or detector knot]` with ears
in separate target fields. The envelope format/version identifies the schema;
rule revision and calibration identity separately identify the algorithms.

The serializers `audiogram_to_dict`, `target_to_dict`, `mapping_to_dict`, and
`prescription_to_dict` in `adapters.json_prescription_store` expose each stage
independently. The UI exports one envelope containing all of them. For example,
this Python API produces just a target without invoking the DSP mapper or BLE:

```python
import json

from tiresias_workstation.adapters.json_prescription_store import target_to_dict
from tiresias_workstation.adapters.pyclarity_camfit import PyClarityCamfitRule
from tiresias_workstation.domain.fittings import Audiogram

audiogram = Audiogram(
    frequencies_hz=(250.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0),
    left_levels_db_hl=(10.0, 10.0, 10.0, 15.0, 30.0, 40.0),
    right_levels_db_hl=(20.0, 20.0, 25.0, 35.0, 45.0, 50.0),
)
target = PyClarityCamfitRule().generate(audiogram)
print(json.dumps(target_to_dict(target), indent=2))
```

Applications using the registry can instead call
`workbench.generate_target(audiogram, rule_id="camfit-compressive-cec1")`.
`workbench.generate(...)` runs both generation and mapping without persistence;
`save(...)` and `export(...)` are explicit independent operations. The Qt page
runs generation/mapping in a background worker and receives the completed
immutable artifact on the UI thread. It never writes a board automatically.

## Extension points

To add another rule, implement `PrescriptionRule`, provide stable metadata, and
register the adapter when constructing `PrescriptionWorkbench`. A rule should
return a full `PrescriptionTarget`; it must not emit SigmaDSP bytes directly.

If a future DSP topology or calibration changes, implement another
`DspPrescriptionMapper` or version the current calibration. Rule outputs remain
portable because the rule and hardware conversion are separate stages.
