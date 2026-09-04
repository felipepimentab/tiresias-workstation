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
            [definition.byte_count for definition in DSP_PARAMETERS],
            [4, 4, 136, 136, 136, 136, 136, 136, 136, 136, 4, 4, 4, 4, 180],
        )

    def test_only_soft_clip_remains_read_only(self):
        """Permit prescription parameters while protecting the Soft Clip LUT."""
        writable = [
            definition
            for definition in DSP_PARAMETERS
            if definition.flags & DspParameterFlag.WRITABLE
        ]

        self.assertEqual(
            [int(definition.parameter_id) for definition in writable],
            list(range(1, 15)),
        )
    def test_public_metadata_matches_golden_contract_crc(self):
        """Pin the byte representation advertised by firmware protocol v4."""
        entries = b"".join(
            bytes(
                (
                    int(definition.parameter_id),
                    int(definition.block_id),
                    definition.byte_count,
                    int(definition.flags),
                )
            )
            for definition in DSP_PARAMETERS
        )

        self.assertEqual(zlib.crc32(entries) & 0xFFFFFFFF, 0x098986FA)
        self.assertEqual(DSP_PARAMETER_CONTRACT_CRC32, 0x098986FA)

    def test_writable_parameters_accept_only_complete_byte_arrays(self):
        """Validate access and size without assigning numerical meaning."""
        writable = DSP_PARAMETERS[0]
        read_only = DSP_PARAMETERS[14]

        self.assertTrue(writable.accepts(b"\x00\x00\x00\x03"))
        self.assertFalse(writable.accepts(b"\x00"))
        self.assertFalse(read_only.accepts(bytes(read_only.byte_count)))


if __name__ == "__main__":
    unittest.main()
