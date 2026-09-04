"""Verify the reusable application-layer prescription loading pipeline."""

from dataclasses import replace
import unittest

from tiresias_workstation.adapters.bundled_prescriptions import N1_PRESCRIPTION
from tiresias_workstation.application.prescription_loader import (
    PrescriptionLoadError,
    PrescriptionLoader,
)
from tiresias_workstation.domain.dsp_contract import DspParameterFlag
from tiresias_workstation.domain.tiresias import ParameterValue
from test_ble_controller import device_session


class FakePrescriptionClient:
    """Record parameter writes and return deterministic board confirmations."""

    def __init__(self, *, fail_parameter_id: int | None = None) -> None:
        """Configure an optional parameter failure."""
        self.fail_parameter_id = fail_parameter_id
        self.writes: list[tuple[int, bytes]] = []
        self.revision = 3

    async def write_parameter(self, parameter_id: int, data: bytes) -> ParameterValue:
        """Confirm one write or raise the configured failure."""
        self.writes.append((parameter_id, data))
        if parameter_id == self.fail_parameter_id:
            raise RuntimeError("simulated board failure")
        self.revision += 1
        return ParameterValue(parameter_id, data, self.revision)


class PrescriptionLoaderTest(unittest.IsolatedAsyncioTestCase):
    """Keep format validation and transfer sequencing independent of Qt."""

    async def test_loads_any_valid_prescription_in_parameter_order(self):
        """Persist a complete profile and report confirmed progress."""
        client = FakePrescriptionClient()
        progress = []

        result = await PrescriptionLoader().load(
            client,
            device_session(),
            N1_PRESCRIPTION,
            progress.append,
        )

        self.assertEqual(
            [parameter_id for parameter_id, _ in client.writes],
            list(range(3, 14)),
        )
        self.assertEqual(len(progress), 11)
        self.assertEqual(progress[-1].completed_bytes, 1100)
        self.assertEqual(result.profile_id, "N1")
        self.assertEqual(result.parameter_count, 11)
        self.assertEqual(result.payload_byte_count, 1100)
        self.assertEqual(result.parameter_revision, 14)

    async def test_rejects_unsupported_format_before_first_write(self):
        """Prevent a partial profile when format metadata is incompatible."""
        client = FakePrescriptionClient()
        unsupported = replace(N1_PRESCRIPTION, format_version=2)

        with self.assertRaisesRegex(PrescriptionLoadError, "unsupported format"):
            await PrescriptionLoader().load(
                client, device_session(), unsupported
            )

        self.assertEqual(client.writes, [])

    async def test_rejects_read_only_device_contract_before_first_write(self):
        """Preflight every profile parameter against the connected board."""
        client = FakePrescriptionClient()
        session = device_session()
        parameters = list(session.parameters)
        parameters[2] = replace(parameters[2], flags=DspParameterFlag.NONE)
        incompatible = replace(session, parameters=tuple(parameters))

        with self.assertRaisesRegex(PrescriptionLoadError, "read-only"):
            await PrescriptionLoader().load(
                client, incompatible, N1_PRESCRIPTION
            )

        self.assertEqual(client.writes, [])

    async def test_runtime_failure_reports_confirmed_partial_progress(self):
        """Identify parameters persisted before a mid-transfer board error."""
        client = FakePrescriptionClient(fail_parameter_id=5)

        with self.assertRaises(PrescriptionLoadError) as raised:
            await PrescriptionLoader().load(
                client, device_session(), N1_PRESCRIPTION
            )

        self.assertEqual(raised.exception.completed_parameters, 2)
        self.assertEqual(raised.exception.parameter_id, 5)
        self.assertEqual(
            [parameter_id for parameter_id, _ in client.writes],
            [3, 4, 5],
        )


if __name__ == "__main__":
    unittest.main()
