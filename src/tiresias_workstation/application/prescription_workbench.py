"""Coordinate rule selection, target generation, mapping, and local storage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from tiresias_workstation.domain.fittings import (
    Audiogram,
    DspPrescriptionMapper,
    Ear,
    GeneratedPrescription,
    GeneratedPrescriptionStore,
    PrescriptionRule,
    PrescriptionRuleMetadata,
    PrescriptionTarget,
)


class PrescriptionWorkbench:
    """Execute the complete custom-prescription workflow without UI concerns."""

    def __init__(
        self,
        rules: tuple[PrescriptionRule, ...],
        mapper: DspPrescriptionMapper,
        store: GeneratedPrescriptionStore,
    ) -> None:
        """Configure selectable rules, DSP mapping, and persistence."""
        self._rules = {rule.metadata.rule_id: rule for rule in rules}
        if len(self._rules) != len(rules):
            raise ValueError("Prescription rule identifiers must be unique.")
        self._mapper = mapper
        self._store = store

    def list_rules(self) -> tuple[PrescriptionRuleMetadata, ...]:
        """Return rule metadata in application display order."""
        return tuple(rule.metadata for rule in self._rules.values())

    def generate(
        self,
        audiogram: Audiogram,
        *,
        rule_id: str,
        name: str,
        ear: Ear,
    ) -> GeneratedPrescription:
        """Generate every artifact stage without persisting it.

        Args:
            audiogram: Validated thresholds for both ears.
            rule_id: Registered prescription rule identifier.
            name: User-facing custom prescription name.
            ear: Ear mapped to the monaural Tiresias DSP path.

        Returns:
            Inspectable audiogram, target, mapping, and board parameter values.

        Raises:
            KeyError: If ``rule_id`` is not registered.
            ValueError: If the custom name is empty or too long.
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("A custom prescription name is required.")
        if len(normalized_name) > 80:
            raise ValueError(
                "Custom prescription names may contain at most 80 characters."
            )
        artifact_id = f"custom-{uuid.uuid4().hex}"
        target = self.generate_target(audiogram, rule_id=rule_id)
        prescription, mapping = self._mapper.map(
            target,
            artifact_id=artifact_id,
            name=normalized_name,
            ear=ear,
        )
        return GeneratedPrescription(
            artifact_id=artifact_id,
            name=normalized_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            target=target,
            mapping=mapping,
            prescription=prescription,
        )

    def generate_target(
        self, audiogram: Audiogram, *, rule_id: str
    ) -> PrescriptionTarget:
        """Generate a rule target independently of hardware mapping and storage.

        Args:
            audiogram: Validated thresholds for both ears.
            rule_id: Registered prescription rule identifier.

        Returns:
            Full two-ear target, also usable with a different DSP mapper.

        Raises:
            KeyError: If the rule identifier is not registered.
        """
        return self._rules[rule_id].generate(audiogram)

    def save(self, artifact: GeneratedPrescription) -> None:
        """Persist one generated artifact in the local catalog."""
        self._store.save(artifact)

    def list_saved(self) -> tuple[GeneratedPrescription, ...]:
        """Return locally saved generated prescriptions."""
        return self._store.list()

    def get_saved(self, artifact_id: str) -> GeneratedPrescription:
        """Return one locally saved artifact."""
        return self._store.get(artifact_id)

    def delete(self, artifact_id: str) -> None:
        """Delete one local artifact by stable identifier."""
        self._store.delete(artifact_id)

    def export(self, artifact: GeneratedPrescription, path: Path) -> None:
        """Export all generation stages as a portable JSON artifact."""
        self._store.export(artifact, path)
