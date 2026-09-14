# Data object workflow

Each of the five [data objects](prescription-data-model.md) has a dedicated
sidebar page. The overlapping Prescriptions, Fitting library and Quick fitting
pages have been removed from the application shell.

| Sidebar group | Page | Role |
| --- | --- | --- |
| Reference & design | Audiograms | Local hearing thresholds used to generate targets |
| Reference & design | Prescription targets | Local acoustic gain intent, linked to the audiogram and rule |
| Reference & design | Detector calibrations | Local measurement data used by the DSP compiler |
| Load to board | Compiled DSP objects | Board-ready compressor LUTs and bias gains |
| Load to board | Output-stage calibration | Board-ready Headroom and SoftClip values |

All five pages support offline creation and inspection. The three reference/design
pages have no load controls. The two board-loadable pages have blue role labels,
gray sidebar selection, and a distinct Board transfer card with the selected payload,
connection instructions, a load action, and confirmed byte progress. Loading
requires a validated connection; the shared controller prevents concurrent loads.
Disconnection disables transfer while leaving the object page open for inspection.

Each saved object retains its name, stable identifier, revision, value and
provenance. The displayed **Output-stage calibration** page continues to use the
`OutputStageConfiguration` domain object and `outputs/` storage collection.

## Working with objects

Use **New**, **View**, **Edit**, **Duplicate**, and **Delete**. The Values preview
shows engineering units; **Provenance & JSON** exposes the complete stored record.
Audiograms also offer a **Graph** tab: left-ear thresholds use blue crosses and
a dashed line; right-ear thresholds use red circles and a solid line. Following
[ASHA audiogram conventions](https://www.asha.org/policy/gl1990-00006/), frequency
uses a logarithmic Hz axis, hearing level increases downward in dB HL, and one
octave spans the same distance as 20 dB. The default axes cover 125–8000 Hz and
−10–120 dB HL and expand to include thresholds outside those ranges.
Creation is the primary action in the page header; selection actions sit below
the list and preview. Search filters objects by name and shows a result count.
On macOS, Command-F focuses search and Command-N opens creation for the current
object page (Control-F/Control-N on other platforms).

Select an audiogram and choose **Generate target…** to carry it into target
generation. Select a target and choose **Compile DSP…** to carry it into
compilation. Saving opens the resulting object's dedicated page. Canceling
leaves the source page unchanged. Both workflows still require explicit generation
and saving; they never load values to the board automatically.

Read-only references remain protected. If another saved object depends on an
object being deleted, an eight-second toast explains the dependency and deletion
is blocked. The full message also remains in the page status.

The layout follows Apple's guidance on
[sidebar hierarchy](https://developer.apple.com/design/human-interface-guidelines/sidebars)
and [toolbar actions](https://developer.apple.com/design/human-interface-guidelines/toolbars),
with neutral navigation, restrained borders, and compact metadata.
The editor validates values before saving. User objects can be renamed and
updated without changing their identity. Duplicate creates a new identity.

The ten Bisgaard audiograms N1–N7 and S1–S3 are fixed, symmetric references.
Their frequencies and thresholds are copied from Tiresias Eval. Custom
audiograms store independent left and right thresholds in dB HL and can use
additional or different frequency rows in Hz. There is no fixed limit on the
number of custom audiograms.

The measured ADAU1787 EVAL detector calibration and the nominal EVAL output-stage
configuration are also read-only references. Protection is enforced by the
storage service as well as the widgets. A JSON file cannot shadow a reference.
Duplicate a reference before customizing it.

## Generate and compile

1. Create or select an audiogram.
2. In Prescription targets, choose **Generate new**, name the target, select the saved
   audiogram and prescriptive rule, then generate and save. Generation runs off
   the UI thread. The target stores the exact two-ear audiogram snapshot, rule
   identity/version/source, frequency and level axes, gains, timing and endpoint
   policy. Its source reference points to the audiogram's stable ID and hash.
3. Targets can be renamed, regenerated with another source/rule, or edited in
   the left/right gain matrices. Gains are dB; columns are acoustic input dB SPL.
   Manual gain edits retain the generating rule and are noted in provenance.
4. Create or select a detector calibration. Its editor stores paired detector
   dBFS and equivalent dB SPL checkpoints for all eight bands, test frequencies,
   detector convention, measurement scope, and provenance. Axes must be finite,
   aligned and strictly increasing. Low endpoints hold or extrapolate; high
   endpoints extrapolate linearly. Current compilation requires the eight
   Tiresias band-centre frequencies.
5. In Compiled DSP objects, choose **Compile new**, select the saved target and calibration,
   choose the monaural board ear, then compile and save. This produces all eight
   136-byte LUTs and three four-byte bias gains. The compiler uses the selected
   calibration, including custom checkpoints, for both LUT and bias generation.
   Editing a compiled object allows renaming or recompilation from selected
   inputs, rather than silently editing payload bytes independently of their
   derivation.

A compiled object retains the exact target and calibration snapshots, references
to both saved objects, selected ear, compiler version, DSP contract fingerprint,
conversion details, and the 1,100 payload bytes. Editing a source does not mutate
existing dependent objects: the library marks changed sources and keeps the old
snapshot. Regenerate/recompile to adopt those edits. Deletion of a referenced
object is blocked until its dependent objects are deleted or regenerated against
other sources. There is no cascading deletion.

## Output-stage configurations

Output objects are independent of detector calibration and compiled fittings.
The EVAL default uses −22 dB headroom, a −27.036 dBFS peak SoftClip threshold,
5:1 compression and a −22 dBFS peak ceiling. It generates the nominal,
underflow-aligned 45-word table, checked against the exact Eval script bytes.
The experimental waveform-dependent calibrated SoftClip table is not a default.

Custom output objects edit these settings and regenerate the complete curve.
They require the DSP program's fixed hold word `00000000` and decay word
`0000013d`. These prerequisites are recorded but not transmitted or independently
verified by the current BLE contract, which exposes only Headroom and the LUT.
Output reference conversion does not replace per-band detector calibration.

## Loading a board

Connect a compatible board, then select **Load selected values to board** in the Board transfer card on either
Compiled DSP objects or Output-stage calibration. Compiled objects load IDs 3–13
(11 parameters / 1,100 bytes). Output objects load Headroom ID 14 and SoftClip ID
15 (2 parameters / 184 bytes). Both use the same preflight, sequential transfer,
confirmed progress and error reporting as the existing prescription loader.
Local reference protection does not prevent loading reference values onto a board.

Firmware and workstation now share contract CRC32 `0x7e8eb66c`: SoftClip is
writable. Firmware with the older fingerprint is rejected at connection; update
both sides together. Wire framing remains protocol v5. Full output loading
requires ATT MTU at least 195.

Each parameter write is atomic. Entire compiled prescriptions and output pairs
are not atomic: an interrupted transfer may leave earlier complete parameters
committed. A lost acknowledgment makes the active parameter's complete commit
uncertain. Errors report progress and instruct retry after communication is
restored. No whole-prescription rollback was added.

## Storage and existing workflows

Under the application's existing `generated-prescriptions` data directory,
`library/` contains separate `audiograms/`, `targets/`, `calibrations/`,
`compiled/`, and `outputs/` JSON collections. Custom file replacement is atomic;
packaged references do not depend on a sibling Eval checkout. Invalid individual
files are logged and excluded without hiding valid objects.

Existing generated-prescription files are imported once into linked audiogram,
target and compiled objects. Their original bytes and legacy files are retained.
Migration markers prevent a deleted imported object from reappearing at the next
startup. Legacy generation used the pinned Eval calibration, which is recorded
on the imported compiled object.

All new generation follows the explicit audiogram → target → compiled object
workflow. Existing linked objects and migrated custom prescriptions remain
available on their respective pages. Legacy combined-artifact serializers and
bundled preset assets remain in the repository for compatibility, but no separate
quick-fitting or preset-loading screen is instantiated by the application.
Generate a target from a standard audiogram and compile it to create loadable
values with explicit provenance.

## Source provenance and verification

The packaged defaults are from `tiresias-eval` revision
`309a644599c4455050583ec56da9f8092b1243a9`. The asset records original paths and
SHA-256 hashes for the Bisgaard CSV, detector calibration JSON and nominal
SoftClip script. The measured detector calibration remains specific to the EVAL
setup described in those records.

Workstation tests use temporary stores, fake transports and offscreen Qt. They
cover protected defaults, CRUD, provenance retention, legacy migration,
calibration-dependent compilation, nominal output bytes, and loading both
artifact types. Firmware verification is compile-only; no firmware tests or
hardware access are introduced.
