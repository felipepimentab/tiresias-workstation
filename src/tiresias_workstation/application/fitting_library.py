"""Coordinate independent fitting libraries, provenance and board-load artifacts."""

from dataclasses import replace
from datetime import datetime, timezone
import uuid

from tiresias_workstation.adapters.library_store import LibraryStore, content_sha256, value_sha256
from tiresias_workstation.adapters.json_prescription_store import target_to_dict
from tiresias_workstation.adapters.sigma_dsp_mapper import SigmaDspMapper
from tiresias_workstation.domain.dsp_contract import DSP_PARAMETER_CONTRACT_CRC32
from tiresias_workstation.domain.fittings import GeneratedPrescription, PrescriptionRule
from tiresias_workstation.domain.library import (
    LIBRARY_KINDS, CompiledDspPrescription, LibraryEntry, SourceReference,
)

COMPILER_VERSION = "tiresias-sigma-5.23-v1"


class FittingLibrary:
    """Manage CRUD and generation without Qt or Bluetooth dependencies."""

    def __init__(self, store: LibraryStore, rules: tuple[PrescriptionRule, ...]) -> None:
        """Configure persistent object storage and available prescriptive rules."""
        self.store = store
        self.rules = {rule.metadata.rule_id: rule for rule in rules}

    def list(self, kind: str) -> tuple[LibraryEntry, ...]:
        """Return references and custom objects for one workflow stage."""
        return self.store.list(kind)

    def get(self, kind: str, item_id: str) -> LibraryEntry:
        """Read one immutable snapshot of a stored object."""
        return self.store.get(kind, item_id)

    @staticmethod
    def reference(entry: LibraryEntry) -> SourceReference:
        """Capture the exact source version used to produce another object."""
        return SourceReference(entry.kind, entry.item_id, content_sha256(entry))

    def save(self, kind: str, name: str, value, *, item_id: str | None = None,
             sources: tuple[SourceReference, ...] = (), provenance: str = "User-created") -> LibraryEntry:
        """Create or update a custom object while retaining stable identity.

        Source deletion is prevented; source changes leave old snapshots intact
        and are surfaced by :meth:`changed_sources` rather than silently applied.
        """
        with self.store.lock:
            previous = self.get(kind, item_id) if item_id else None
            if previous and previous.read_only:
                raise ValueError("Reference objects are read-only. Duplicate to customize.")
            item_id = item_id or f"user-{uuid.uuid4().hex}"
            for source in sources:
                self.get(source.kind, source.item_id)
            if kind == "targets" and sources:
                snapshot = LibraryEntry("snapshot", "Snapshot", "audiograms", value.audiogram)
                if self.reference(snapshot).sha256 != sources[0].sha256:
                    raise ValueError("Target audiogram does not match its source snapshot.")
            if kind == "compiled" and len(sources) == 2:
                target_hash = value_sha256(target_to_dict(value.artifact.target))
                calibration_snapshot = LibraryEntry("snapshot", "Snapshot", "calibrations", value.calibration)
                if target_hash != sources[0].sha256 or self.reference(calibration_snapshot).sha256 != sources[1].sha256:
                    raise ValueError("Compiled values do not match the selected source snapshots.")
            expected_sources = {"targets": ("audiograms",), "compiled": ("targets", "calibrations")}.get(kind, ())
            if tuple(source.kind for source in sources) != expected_sources:
                raise ValueError(f"{kind} requires source references {expected_sources}.")
            if kind == "compiled":
                artifact = value.artifact
                value = replace(value, artifact=replace(
                    artifact, artifact_id=item_id, name=name.strip(),
                    prescription=replace(artifact.prescription, profile_id=item_id, display_name=name.strip()),
                ))
            entry = LibraryEntry(item_id, name.strip(), kind, value, sources,
                                 revision=previous.revision + 1 if previous else 1, provenance=provenance)
            self.store.save(entry)
            return entry

    def duplicate(self, entry: LibraryEntry, name: str) -> LibraryEntry:
        """Copy a reference or custom object into a new editable identity."""
        return self.save(entry.kind, name, entry.value, sources=entry.sources,
                         provenance=f"Copy of {entry.item_id}: {entry.provenance}")

    def delete(self, kind: str, item_id: str) -> None:
        """Delete a custom object unless other saved objects still reference it."""
        with self.store.lock:
            if self.get(kind, item_id).read_only:
                raise ValueError("Reference objects cannot be deleted.")
            dependents = [entry.name for category in LIBRARY_KINDS for entry in self.list(category)
                          if any(source.kind == kind and source.item_id == item_id for source in entry.sources)]
            if dependents:
                raise ValueError("Delete or regenerate dependent objects first: " + ", ".join(dependents))
            self.store.delete(kind, item_id)

    def changed_sources(self, entry: LibraryEntry) -> tuple[str, ...]:
        """Report upstream edits while preserving the saved generation snapshot."""
        changed = []
        for source in entry.sources:
            try:
                current = self.get(source.kind, source.item_id)
                if content_sha256(current) != source.sha256:
                    changed.append(current.name)
                changed.extend(self.changed_sources(current))
            except KeyError:
                changed.append(source.item_id)
        return tuple(dict.fromkeys(changed))

    def generate_target(self, audiogram: LibraryEntry, rule_id: str):
        """Generate portable fitting intent without detector calibration."""
        if audiogram.kind != "audiograms":
            raise ValueError("Select an audiogram to generate a target.")
        return self.rules[rule_id].generate(audiogram.value)

    def compile(self, target: LibraryEntry, calibration: LibraryEntry, ear: str,
                name: str) -> CompiledDspPrescription:
        """Compile a selected target and measured calibration for one ear."""
        if target.kind != "targets" or calibration.kind != "calibrations":
            raise ValueError("Compilation needs a target and detector calibration.")
        item_id = f"user-{uuid.uuid4().hex}"
        prescription, mapping = SigmaDspMapper(calibration.value).map(
            target.value, artifact_id=item_id, name=name, ear=ear,
        )
        artifact = GeneratedPrescription(item_id, name, datetime.now(timezone.utc).isoformat(),
                                         target.value, mapping, prescription)
        return CompiledDspPrescription(artifact, calibration.value, COMPILER_VERSION,
                                       DSP_PARAMETER_CONTRACT_CRC32)

    def board_prescription(self, entry: LibraryEntry):
        """Return complete board values for compiled or output-stage objects."""
        if entry.kind == "compiled":
            if entry.value.contract_crc32 != DSP_PARAMETER_CONTRACT_CRC32:
                raise ValueError("Recompile this prescription for the current DSP contract.")
            return entry.value.artifact.prescription
        if entry.kind == "outputs":
            return entry.value.prescription(entry.item_id, entry.name)
        raise ValueError("Only compiled prescriptions and output configurations can be loaded.")

    def import_legacy(self, artifact: GeneratedPrescription) -> None:
        """Split an existing bundled artifact once, preserving original bytes.

        Legacy generation used the pinned Eval calibration. New objects retain
        its target and audiogram snapshots and acquire explicit source links.
        """
        with self.store.lock:
            if self.store.was_imported(artifact.artifact_id):
                return
            try:
                self.get("compiled", artifact.artifact_id)
                self.store.mark_imported(artifact.artifact_id)
                return
            except KeyError:
                pass
            audio = self.save("audiograms", artifact.name + " audiogram", artifact.target.audiogram)
            target = self.save("targets", artifact.name + " target", artifact.target,
                               sources=(self.reference(audio),), provenance="Imported legacy target")
            calibration = self.get("calibrations", "eval-detector")
            compiled = CompiledDspPrescription(artifact, calibration.value, COMPILER_VERSION,
                                               DSP_PARAMETER_CONTRACT_CRC32)
            entry = LibraryEntry(artifact.artifact_id, artifact.name, "compiled", compiled,
                                 (self.reference(target), self.reference(calibration)),
                                 provenance="Imported legacy generated prescription")
            self.store.save(entry)
            self.store.mark_imported(artifact.artifact_id)


class LibraryPrescriptionCatalog:
    """Expose saved compiled objects to the existing board-loading catalog."""

    def __init__(self, library: FittingLibrary) -> None:
        """Share the same library used by the editors."""
        self.library = library

    def list_prescriptions(self):
        """List compatible compiled prescriptions; outputs use their own editor."""
        return tuple(self.library.board_prescription(entry) for entry in self.library.list("compiled")
                     if entry.value.contract_crc32 == DSP_PARAMETER_CONTRACT_CRC32)

    def get(self, profile_id: str):
        """Resolve a selected saved compiled prescription."""
        return self.library.board_prescription(self.library.get("compiled", profile_id))
