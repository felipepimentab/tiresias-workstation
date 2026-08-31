"""Verify integrity and DSP-contract mapping of bundled prescriptions."""

import unittest

from tiresias_workstation.adapters.bundled_prescriptions import (
    BUNDLED_PRESCRIPTIONS,
    BUNDLED_PRESCRIPTIONS_BY_ID,
    N1_PRESCRIPTION,
)
from tiresias_workstation.domain.dsp_contract import DspParameterId


class BundledPrescriptionTests(unittest.TestCase):
    """Keep imported parameter bytes usable through stable workstation IDs."""

    def test_each_profile_contains_eight_luts_and_three_bias_values(self):
        """Map every script value to its fixed DSP parameter identifier."""
        expected_ids = tuple(
            DspParameterId(parameter_id) for parameter_id in range(3, 14)
        )

        for prescription in BUNDLED_PRESCRIPTIONS:
            self.assertEqual(
                tuple(
                    parameter.parameter_id
                    for parameter in prescription.parameters
                ),
                expected_ids,
            )
            self.assertEqual(
                [len(parameter.data) for parameter in prescription.parameters],
                [136] * 8 + [4] * 3,
            )
            self.assertEqual(prescription.payload_byte_count, 1100)

    def test_profile_integrity_and_provenance_are_pinned(self):
        """Detect byte changes and retain exact SigmaStudio source identities."""
        expected_hashes = {
            "N1": (
                "31ffb9f09da901e5ac47454c0e8cb95897d54c8269a07f00365c86d1f272243d",
                "d27bcbb68121dc5ca99a756f1eac2f9c8fe57280982069cf2fcf63af81aa26f1",
            ),
            "N2": (
                "b1db17012431608e734ac6aad93943066f06b063da81a34ad0df35b378777235",
                "1d3665ee73e1f28de6b2d6adbff663fcf2ffe3f54985a09f7d0da1bddeb02ca0",
            ),
            "N3": (
                "7d052d960271ecab708ab321e56500382a29c7211c3e5a65ed8713d3b4272b52",
                "03306990397785a38795f06bc8c96325623c1ca32ab2f6c7cbece2a3730f72b2",
            ),
            "N4": (
                "730ae12fbba2f44f91e48981d3999dd250cf25973359642e19bed6a5baf41515",
                "866b6d57fc8211e3751c0d19ea04fb7098a22404839b163890eff99dec35325f",
            ),
            "N5": (
                "d1dca7e6d6f820e619d2a810bf3034bed6ff25c2114a267aac6d5d525b868164",
                "f07dfbac37a33b855975b0673b6ddbb9dffc94a747ecd2a94972b972dd2c16bd",
            ),
            "N6": (
                "40cb88ea77a1b5d80c9e4859cc8febc5e33a5d4e29f20c20d4a64a852a7aec17",
                "6697cfb02e6d14ee32e208c3e6728dbdc133829ffa9b09c2c9719eb1455176b1",
            ),
            "N7": (
                "072d219ccb4c79ecb965da28572427b2d73479846fe2e265130ced2b4827b048",
                "4091692572db008cf8f83441826e0ed955e58af0009995dde21010fd2ad114f8",
            ),
            "S1": (
                "9f59d5a13b9b18934763f72c05d58d4cb7e222faacd439dbbecb74bc74f86673",
                "f1f46b3dd2a653955a6912adc2c8fb1f3035c842c4254d24f5657b20aaff0b9b",
            ),
            "S2": (
                "8ba781ef3976e1e16ea1ffc75741323c4ae8d5149542513d784d684d14438d25",
                "e3716b6c655abdd52b55b900fd10dbb80c81a128694a65b607cf03e341787e42",
            ),
            "S3": (
                "7c73b2c02ee42c1730953d320abece6cec03bbb26407a7c147d5e244e34717d0",
                "79f221cf595e31f93a22249a6381b64de8cd6229450debf081e54a36f05878b7",
            ),
        }

        for profile_id, (integrity_hash, source_hash) in expected_hashes.items():
            prescription = BUNDLED_PRESCRIPTIONS_BY_ID[profile_id]
            self.assertEqual(prescription.sha256, integrity_hash)
            self.assertEqual(prescription.source.sha256, source_hash)

    def test_each_profile_reuses_its_script_bias_for_all_three_gains(self):
        """Apply each extracted bias word to all three phase-compensation IDs."""
        expected_biases = {
            "N1": "00c7ba20",
            "N2": "011a285c",
            "N3": "01f5c151",
            "N4": "037c42c7",
            "N5": "037c42c7",
            "N6": "0474cd1b",
            "N7": "0474cd1b",
            "S1": "025fe3e7",
            "S2": "0474cd1b",
            "S3": "0438ffaa",
        }

        for profile_id, expected_bias in expected_biases.items():
            prescription = BUNDLED_PRESCRIPTIONS_BY_ID[profile_id]
            for parameter_id in (
                DspParameterId.PHASE_COMP_GAIN_1,
                DspParameterId.PHASE_COMP_GAIN_2,
                DspParameterId.PHASE_COMP_GAIN_3,
            ):
                self.assertEqual(
                    prescription.parameter(parameter_id).data,
                    bytes.fromhex(expected_bias),
                )

    def test_all_standard_audiograms_are_available_from_the_catalog(self):
        """Expose all ten prescriptions in stable profile order."""
        self.assertEqual(
            tuple(
                prescription.profile_id
                for prescription in BUNDLED_PRESCRIPTIONS
            ),
            ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "S1", "S2", "S3"),
        )
        self.assertEqual(len(BUNDLED_PRESCRIPTIONS_BY_ID), 10)
        self.assertIs(BUNDLED_PRESCRIPTIONS_BY_ID["N1"], N1_PRESCRIPTION)


if __name__ == "__main__":
    unittest.main()
