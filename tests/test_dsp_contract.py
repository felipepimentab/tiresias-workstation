"""Verify invariants of the fixed MVP DSP contract."""

import zlib
import unittest

from tiresias_workstation.domain.dsp_contract import (
    DSP_BLOCKS,
    DSP_BLOCKS_BY_ID,
    DSP_PARAMETER_CONTRACT_CRC32,
    DSP_PARAMETERS,
    DSP_PARAMETERS_BY_ID,
    DspParameterFlag,
)


class DspContractTests(unittest.TestCase):
    """Keep fixed identifiers and parameter metadata internally coherent."""

    def test_identifiers_are_unique_nonzero_bytes(self):
        """Require each contract namespace to use unique one-byte IDs."""
        block_ids = [int(definition.block_id) for definition in DSP_BLOCKS]
        parameter_ids = [
            int(definition.parameter_id) for definition in DSP_PARAMETERS
        ]

        self.assertEqual(len(block_ids), len(set(block_ids)))
        self.assertEqual(len(parameter_ids), len(set(parameter_ids)))
        self.assertTrue(all(0 < identifier <= 0xFF for identifier in block_ids))
        self.assertTrue(
            all(0 < identifier <= 0xFF for identifier in parameter_ids)
        )

    def test_every_parameter_references_a_known_block(self):
        """Reject parameters that cannot be grouped in the workstation UI."""
        self.assertTrue(
            all(
                definition.block_id in DSP_BLOCKS_BY_ID
                for definition in DSP_PARAMETERS
            )
        )

    def test_fixed_catalog_has_expected_shape(self):
        """Pin the curated MVP block, parameter, and LUT sizes."""
        self.assertEqual(len(DSP_BLOCKS), 15)
        self.assertEqual(len(DSP_PARAMETERS), 15)
        self.assertEqual(len(DSP_BLOCKS_BY_ID), len(DSP_BLOCKS))
        self.assertEqual(len(DSP_PARAMETERS_BY_ID), len(DSP_PARAMETERS))
        self.assertEqual(
            [definition.word_count for definition in DSP_PARAMETERS],
            [1, 1, 34, 34, 34, 34, 34, 34, 34, 34, 1, 1, 1, 1, 45],
        )

    def test_only_scalar_controls_are_writable(self):
        """Keep multi-word LUT writes disabled until transport support exists."""
        writable = [
            definition
            for definition in DSP_PARAMETERS
            if definition.flags & DspParameterFlag.WRITABLE
        ]

        self.assertEqual(
            [int(definition.parameter_id) for definition in writable],
            [1, 2, 11, 12, 13, 14],
        )
        self.assertEqual(
            [
                int(definition.parameter_id)
                for definition in writable
                if definition.flags & DspParameterFlag.INTEGER
            ],
            [1, 2],
        )

    def test_public_metadata_matches_golden_contract_crc(self):
        """Pin the byte representation advertised by firmware protocol v2."""
        entries = b"".join(
            bytes(
                (
                    int(definition.parameter_id),
                    int(definition.block_id),
                    definition.word_count,
                    int(definition.flags),
                )
            )
            for definition in DSP_PARAMETERS
        )

        self.assertEqual(zlib.crc32(entries) & 0xFFFFFFFF, 0xF62C1808)
        self.assertEqual(DSP_PARAMETER_CONTRACT_CRC32, 0xF62C1808)

    def test_scalar_constraints_match_firmware_validation(self):
        """Keep selector and Q5.23 write ranges synchronized."""
        adc, source = DSP_PARAMETERS[:2]
        gains = DSP_PARAMETERS[10:14]

        self.assertTrue(adc.accepts(3))
        self.assertFalse(adc.accepts(4))
        self.assertTrue(source.accepts(1))
        self.assertFalse(source.accepts(2))
        self.assertTrue(all(definition.accepts(0x00800000) for definition in gains))
        self.assertTrue(all(not definition.accepts(1) for definition in gains))


if __name__ == "__main__":
    unittest.main()
