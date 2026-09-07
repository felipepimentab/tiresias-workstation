"""Load pinned Eval references without requiring its checkout at runtime."""

from importlib.resources import files
import json

from tiresias_workstation.domain.fittings import Audiogram
from tiresias_workstation.domain.library import CalibrationBand, DeviceCalibration, LibraryEntry, OutputStageConfiguration


def reference_entries() -> tuple[LibraryEntry, ...]:
    """Return ten immutable audiograms, detector calibration and nominal output."""
    raw = json.loads(files("tiresias_workstation.adapters.library_assets").joinpath("eval_defaults.json").read_text())
    provenance = f"tiresias-eval@{raw['eval_revision']}"
    entries = []
    for row in raw["audiograms"]:
        keys = [key for key in row if key.startswith("hl_")]
        levels = tuple(float(row[key]) for key in keys)
        entries.append(LibraryEntry(
            row["profile"], f"{row['profile']} · {row['category']}", "audiograms",
            Audiogram(tuple(float(key[3:]) for key in keys), levels, levels),
            read_only=True, provenance=provenance,
        ))
    calibration = raw["calibration"]
    bands = tuple(CalibrationBand(
        band["frequency_hz"], tuple(band["detector_dbfs"]),
        tuple(band["equivalent_input_level_db_spl"]), band["low_level_floor_detected"],
    ) for band in calibration["measured_band_calibration"].values())
    entries.append(LibraryEntry(
        "eval-detector", "ADAU1787 EVAL detector calibration", "calibrations",
        DeviceCalibration(calibration["calibration_id"], calibration["scope"],
                          "Per-band SigmaDSP RMS detector dBFS; EVAL unity/identification measurements",
                          bands, provenance), read_only=True, provenance=provenance,
    ))
    output = OutputStageConfiguration(-22.0, -27.036, 5.0, -22.0, provenance)
    if output.parameters()[1].data.hex() != raw["softclip_nominal_hex"]:
        raise ValueError("Nominal output compiler differs from the pinned Eval table.")
    entries.append(LibraryEntry(
        "eval-output", "EVAL nominal output · −22 dB", "outputs", output,
        read_only=True, provenance=provenance,
    ))
    return tuple(entries)


def default_calibration() -> DeviceCalibration:
    """Return the pinned measured detector conversion used by default."""
    return next(entry.value for entry in reference_entries() if entry.kind == "calibrations")
