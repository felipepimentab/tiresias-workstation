"""Decode presentation values from fixed-contract DSP parameter bytes.

The BLE protocol continues to transport and persist opaque byte arrays. These
helpers assign numerical meaning only to complete copies used for workstation
display and editor controls.
"""


SIGMA_WORD_BYTES = 4
SIGMA_FRACTIONAL_BITS = 23
SIGMA_WORD_BITS = 28


def decode_sigma_5_23_words(data: bytes) -> tuple[float, ...]:
    """Decode big-endian SigmaDSP 5.23 words as signed floating-point values.

    SigmaDSP parameter words occupy 28 significant bits in each four-byte
    transfer word. Bit 27 is the sign bit and the upper nibble is ignored.

    Args:
        data: Complete sequence of four-byte, big-endian parameter words.

    Returns:
        One dimensionless floating-point value per input word.

    Raises:
        ValueError: If ``data`` is not aligned to complete four-byte words.
    """
    if len(data) % SIGMA_WORD_BYTES:
        raise ValueError("SigmaDSP 5.23 data must contain complete four-byte words.")

    values: list[float] = []
    value_mask = (1 << SIGMA_WORD_BITS) - 1
    sign_bit = 1 << (SIGMA_WORD_BITS - 1)
    signed_range = 1 << SIGMA_WORD_BITS
    scale = float(1 << SIGMA_FRACTIONAL_BITS)
    for offset in range(0, len(data), SIGMA_WORD_BYTES):
        integer = int.from_bytes(data[offset : offset + SIGMA_WORD_BYTES], "big")
        integer &= value_mask
        if integer & sign_bit:
            integer -= signed_range
        values.append(integer / scale)
    return tuple(values)


def decode_u32_word(data: bytes) -> int:
    """Decode one four-byte, big-endian unsigned selector value.

    Args:
        data: Exactly one complete selector word.

    Returns:
        Unsigned 32-bit integer represented by ``data``.

    Raises:
        ValueError: If ``data`` is not exactly four bytes.
    """
    if len(data) != SIGMA_WORD_BYTES:
        raise ValueError("A selector value must contain exactly four bytes.")
    return int.from_bytes(data, byteorder="big", signed=False)


def encode_u32_word(value: int) -> bytes:
    """Encode an unsigned selector value as one big-endian word.

    Args:
        value: Integer in the unsigned 32-bit range.

    Returns:
        Four-byte representation suitable for the opaque BLE write path.

    Raises:
        ValueError: If ``value`` is outside the unsigned 32-bit range.
    """
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("A selector value must fit in an unsigned 32-bit word.")
    return value.to_bytes(SIGMA_WORD_BYTES, byteorder="big", signed=False)
