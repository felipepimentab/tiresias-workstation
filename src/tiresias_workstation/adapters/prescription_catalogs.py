"""Compose immutable bundled profiles with mutable local prescriptions."""

from tiresias_workstation.domain.fittings import GeneratedPrescriptionStore
from tiresias_workstation.domain.prescriptions import Prescription, PrescriptionCatalog


class SavedPrescriptionCatalog:
    """Expose locally stored artifacts through the prescription catalog API."""

    def __init__(self, store: GeneratedPrescriptionStore) -> None:
        """Configure the generated-artifact source."""
        self._store = store

    def list_prescriptions(self) -> tuple[Prescription, ...]:
        """Return the transport-ready value from every saved artifact."""
        return tuple(artifact.prescription for artifact in self._store.list())

    def get(self, profile_id: str) -> Prescription:
        """Return one saved transport-ready prescription."""
        return self._store.get(profile_id).prescription


class CompositePrescriptionCatalog:
    """Present multiple catalogs as one ordered, duplicate-free catalog."""

    def __init__(self, *catalogs: PrescriptionCatalog) -> None:
        """Configure catalogs in display and lookup priority order."""
        self._catalogs = catalogs

    def list_prescriptions(self) -> tuple[Prescription, ...]:
        """Return all profiles while rejecting ambiguous identifiers."""
        result: list[Prescription] = []
        seen: set[str] = set()
        for catalog in self._catalogs:
            for prescription in catalog.list_prescriptions():
                if prescription.profile_id in seen:
                    raise ValueError(
                        "Duplicate prescription identifier "
                        f"{prescription.profile_id!r}."
                    )
                seen.add(prescription.profile_id)
                result.append(prescription)
        return tuple(result)

    def get(self, profile_id: str) -> Prescription:
        """Return the first catalog entry matching a stable identifier."""
        for catalog in self._catalogs:
            try:
                return catalog.get(profile_id)
            except KeyError:
                continue
        raise KeyError(profile_id)
