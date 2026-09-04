"""Expose the validated standard-audiogram prescription catalog."""

from tiresias_workstation.adapters.prescription_assets.n1 import N1_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.n2 import N2_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.n3 import N3_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.n4 import N4_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.n5 import N5_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.n6 import N6_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.n7 import N7_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.s1 import S1_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.s2 import S2_PRESCRIPTION
from tiresias_workstation.adapters.prescription_assets.s3 import S3_PRESCRIPTION
from tiresias_workstation.domain.prescriptions import Prescription


BUNDLED_PRESCRIPTIONS = (
    N1_PRESCRIPTION,
    N2_PRESCRIPTION,
    N3_PRESCRIPTION,
    N4_PRESCRIPTION,
    N5_PRESCRIPTION,
    N6_PRESCRIPTION,
    N7_PRESCRIPTION,
    S1_PRESCRIPTION,
    S2_PRESCRIPTION,
    S3_PRESCRIPTION,
)
BUNDLED_PRESCRIPTIONS_BY_ID = {
    prescription.profile_id: prescription for prescription in BUNDLED_PRESCRIPTIONS
}


class BundledPrescriptionCatalog:
    """Expose validated workstation assets through the catalog interface."""

    def list_prescriptions(self) -> tuple[Prescription, ...]:
        """Return every bundled prescription in standard-audiogram order."""
        return BUNDLED_PRESCRIPTIONS

    def get(self, profile_id: str) -> Prescription:
        """Return one bundled prescription by stable identifier.

        Args:
            profile_id: Stable standard-audiogram identifier.

        Returns:
            Matching bundled prescription.

        Raises:
            KeyError: If the profile is not bundled.
        """
        return BUNDLED_PRESCRIPTIONS_BY_ID[profile_id]


BUNDLED_PRESCRIPTION_CATALOG = BundledPrescriptionCatalog()
