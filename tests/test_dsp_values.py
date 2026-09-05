"""Verify presentation-only decoding of typed DSP parameter values."""

import unittest

from tiresias_workstation.domain.dsp_values import (
    decode_sigma_5_23_words,
    decode_u32_word,
    encode_u32_word,
)


class DspValueTests(unittest.TestCase):
    """Exercise SigmaDSP fixed-point and unsigned selector conversions."""

    def test_decodes_signed_big_endian_sigma_5_23_words(self):
        """Decode positive, fractional, and 28-bit negative values."""
        data = bytes.fromhex("00 80 00 00 00 40 00 00 0F C0 00 00")

        self.assertEqual(decode_sigma_5_23_words(data), (1.0, 0.5, -0.5))

    def test_rejects_incomplete_sigma_word(self):
        """Require complete words instead of silently truncating display data."""
        with self.assertRaisesRegex(ValueError, "complete four-byte words"):
            decode_sigma_5_23_words(b"\x00\x80\x00")

    def test_round_trips_unsigned_selector_words(self):
        """Keep switch encoding isolated from the opaque transport path."""
        for value in (0, 1, 3, 0xFFFFFFFF):
            with self.subTest(value=value):
                self.assertEqual(decode_u32_word(encode_u32_word(value)), value)

        with self.assertRaises(ValueError):
            decode_u32_word(b"\x00")
        with self.assertRaises(ValueError):
            encode_u32_word(-1)


if __name__ == "__main__":
    unittest.main()
