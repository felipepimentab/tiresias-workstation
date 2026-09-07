"""Persist separate fitting objects as versioned JSON with protected defaults.

Each file replacement is atomic. Built-in references are loaded from packaged
assets and cannot be shadowed, updated or deleted by user files.
"""

from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
import re
from threading import RLock

from tiresias_workstation.adapters.json_prescription_store import (
    artifact_from_dict, artifact_to_dict, target_from_dict, target_to_dict,
)
from tiresias_workstation.adapters.library_defaults import reference_entries
from tiresias_workstation.domain.fittings import Audiogram
from tiresias_workstation.domain.library import (
    LIBRARY_KINDS, CalibrationBand, CompiledDspPrescription, DeviceCalibration,
    LibraryEntry, OutputStageConfiguration, SourceReference,
)

_LOG = logging.getLogger(__name__)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def value_to_dict(entry: LibraryEntry) -> dict:
    """Encode the value separately from editable catalog metadata."""
    if entry.kind == "targets":
        return target_to_dict(entry.value)
    if entry.kind == "compiled":
        return {
            "artifact": artifact_to_dict(entry.value.artifact),
            "calibration": asdict(entry.value.calibration),
            "compiler_version": entry.value.compiler_version,
            "contract_crc32": entry.value.contract_crc32,
        }
    return asdict(entry.value)


def calibration_from_dict(value: dict) -> DeviceCalibration:
    """Decode immutable band measurements and their endpoint policies."""
    return DeviceCalibration(
        value["calibration_id"], value["scope"], value["detector_convention"],
        tuple(CalibrationBand(b["frequency_hz"], tuple(b["detector_dbfs"]),
                              tuple(b["equivalent_input_db_spl"]), b["hold_low"])
              for b in value["bands"]), value["provenance"],
    )


def entry_to_dict(entry: LibraryEntry) -> dict:
    """Serialize one library envelope, preserving generation source hashes."""
    return {
        "format": "tiresias-library", "version": 1, "item_id": entry.item_id,
        "name": entry.name, "kind": entry.kind, "revision": entry.revision,
        "sources": [asdict(source) for source in entry.sources],
        "provenance": entry.provenance, "value": value_to_dict(entry),
    }


def entry_from_dict(data: dict) -> LibraryEntry:
    """Validate a user artifact; file contents cannot grant read-only identity."""
    if data.get("format") != "tiresias-library" or data.get("version") != 1:
        raise ValueError("Unsupported library format or version.")
    kind, value = data["kind"], data["value"]
    if kind == "audiograms":
        result = Audiogram(*(tuple(value[key]) for key in (
            "frequencies_hz", "left_levels_db_hl", "right_levels_db_hl")))
    elif kind == "targets":
        result = target_from_dict(value)
    elif kind == "calibrations":
        result = calibration_from_dict(value)
    elif kind == "compiled":
        result = CompiledDspPrescription(
            artifact_from_dict(value["artifact"]), calibration_from_dict(value["calibration"]),
            value["compiler_version"], value["contract_crc32"],
        )
    elif kind == "outputs":
        result = OutputStageConfiguration(**value)
    else:
        raise ValueError("Unknown library object kind.")
    return LibraryEntry(data["item_id"], data["name"], kind, result,
                        tuple(SourceReference(**source) for source in data["sources"]),
                        revision=data["revision"], provenance=data["provenance"])


def content_sha256(entry: LibraryEntry) -> str:
    """Hash object content without names or filesystem-dependent metadata."""
    return value_sha256(value_to_dict(entry))


def value_sha256(value: dict) -> str:
    """Hash JSON values with equivalent integer/float coordinates normalized."""
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(value) for value in item]
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return float(item)
        return item
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class LibraryStore:
    """Own JSON persistence and enforce immutable packaged references."""

    def __init__(self, directory: Path) -> None:
        """Configure a library root without writing to disk."""
        self.directory = directory
        self.lock = RLock()
        self._defaults = {(e.kind, e.item_id): e for e in reference_entries()}

    def _path(self, kind: str, item_id: str) -> Path:
        """Resolve validated identities within the dedicated library root."""
        if kind not in LIBRARY_KINDS or not isinstance(item_id, str) or not _ID.fullmatch(item_id):
            raise ValueError("Invalid library identity.")
        return self.directory / kind / f"{item_id}.json"

    def get(self, kind: str, item_id: str) -> LibraryEntry:
        """Read one default or user object, validating its file identity."""
        with self.lock:
            path = self._path(kind, item_id)
            if (kind, item_id) in self._defaults:
                return self._defaults[kind, item_id]
            if not path.is_file():
                raise KeyError(f"Missing {kind} object: {item_id}")
            entry = entry_from_dict(json.loads(path.read_text(encoding="utf-8")))
            if entry.kind != kind or entry.item_id != item_id:
                raise ValueError("Library identity does not match its filename.")
            return entry

    def list(self, kind: str) -> tuple[LibraryEntry, ...]:
        """List references first and valid custom objects by display name."""
        with self.lock:
            if kind not in LIBRARY_KINDS:
                raise ValueError("Unknown library kind.")
            entries = [entry for entry in self._defaults.values() if entry.kind == kind]
            for path in (self.directory / kind).glob("*.json"):
                if (kind, path.stem) in self._defaults:
                    continue
                try:
                    entries.append(self.get(kind, path.stem))
                except (ValueError, TypeError, KeyError, OSError):
                    _LOG.warning("Ignoring invalid library object %s", path, exc_info=True)
            return tuple(sorted(entries, key=lambda e: (not e.read_only, e.name.casefold(), e.item_id)))

    def save(self, entry: LibraryEntry) -> None:
        """Replace one user object atomically; reject writes to references."""
        with self.lock:
            path = self._path(entry.kind, entry.item_id)
            if entry.read_only or (entry.kind, entry.item_id) in self._defaults:
                raise ValueError("Reference objects are read-only. Duplicate to customize.")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(entry_to_dict(entry), indent=2, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(path)

    def was_imported(self, item_id: str) -> bool:
        """Remember migration even after a user deletes its compiled result."""
        self._path("compiled", item_id)
        return (self.directory / "legacy-imports" / item_id).is_file()

    def mark_imported(self, item_id: str) -> None:
        """Record successful migration without changing the original legacy file."""
        self._path("compiled", item_id)
        marker = self.directory / "legacy-imports" / item_id
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("Imported; do not restore after library deletion.\n")

    def delete(self, kind: str, item_id: str) -> None:
        """Delete a custom object while preserving packaged references."""
        with self.lock:
            if self.get(kind, item_id).read_only:
                raise ValueError("Reference objects cannot be deleted.")
            self._path(kind, item_id).unlink()
