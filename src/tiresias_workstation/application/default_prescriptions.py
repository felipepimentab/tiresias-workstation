"""Assemble the default prescription rules, mapping, and local catalogs."""

from pathlib import Path

from tiresias_workstation.adapters.bundled_prescriptions import (
    BUNDLED_PRESCRIPTION_CATALOG,
)
from tiresias_workstation.adapters.json_prescription_store import (
    JsonPrescriptionStore,
)
from tiresias_workstation.adapters.prescription_catalogs import (
    CompositePrescriptionCatalog,
    SavedPrescriptionCatalog,
)
from tiresias_workstation.adapters.pyclarity_camfit import PyClarityCamfitRule
from tiresias_workstation.adapters.sigma_dsp_mapper import SigmaDspMapper
from tiresias_workstation.application.prescription_workbench import (
    PrescriptionWorkbench,
)
from tiresias_workstation.domain.prescriptions import PrescriptionCatalog


def create_default_prescription_services(
    directory: Path,
) -> tuple[PrescriptionWorkbench, PrescriptionCatalog]:
    """Create application services sharing one local JSON store.

    Args:
        directory: Application-owned directory for generated artifacts.

    Returns:
        Workbench for fitting operations and combined bundled/local catalog.
    """
    store = JsonPrescriptionStore(directory)
    workbench = PrescriptionWorkbench(
        (PyClarityCamfitRule(),),
        SigmaDspMapper(),
        store,
    )
    catalog = CompositePrescriptionCatalog(
        BUNDLED_PRESCRIPTION_CATALOG,
        SavedPrescriptionCatalog(store),
    )
    return workbench, catalog
