"""Define the fixed MVP DSP block and parameter contract.

This module is the workstation-owned mirror of the firmware contract. The
numeric identifiers and parameter metadata must remain synchronized with
``src/codec/dsp_parameter_catalog.h`` in the firmware repository.
"""

from dataclasses import dataclass
from enum import IntEnum, IntFlag


DSP_PARAMETER_CONTRACT_CRC32 = 0x22045C5C


class DspBlockId(IntEnum):
    """Stable identifiers for DSP processing blocks."""

    ADC_SELECT = 1
    SOURCE_SELECT = 2
    BAND_1_COMPRESSOR = 3
    BAND_2_COMPRESSOR = 4
    BAND_3_COMPRESSOR = 5
    BAND_4_COMPRESSOR = 6
    BAND_5_COMPRESSOR = 7
    BAND_6_COMPRESSOR = 8
    BAND_7_COMPRESSOR = 9
    BAND_8_COMPRESSOR = 10
    PHASE_COMP_GAIN_1 = 11
    PHASE_COMP_GAIN_2 = 12
    PHASE_COMP_GAIN_3 = 13
    OUTPUT_HEADROOM = 14
    SOFT_CLIP = 15


class DspParameterId(IntEnum):
    """Stable identifiers used by DSP parameter requests."""

    ADC_SELECT = 1
    SOURCE_SELECT = 2
    BAND_1_COMPRESSOR_LUT = 3
    BAND_2_COMPRESSOR_LUT = 4
    BAND_3_COMPRESSOR_LUT = 5
    BAND_4_COMPRESSOR_LUT = 6
    BAND_5_COMPRESSOR_LUT = 7
    BAND_6_COMPRESSOR_LUT = 8
    BAND_7_COMPRESSOR_LUT = 9
    BAND_8_COMPRESSOR_LUT = 10
    PHASE_COMP_GAIN_1 = 11
    PHASE_COMP_GAIN_2 = 12
    PHASE_COMP_GAIN_3 = 13
    OUTPUT_HEADROOM_GAIN = 14
    SOFT_CLIP_LUT = 15


class DspParameterFlag(IntFlag):
    """Access properties for an opaque parameter byte array."""

    NONE = 0
    WRITABLE = 1 << 0


@dataclass(frozen=True, slots=True)
class DspBlockDefinition:
    """Human-readable definition of one fixed DSP processing block."""

    block_id: DspBlockId
    name: str


@dataclass(frozen=True, slots=True)
class DspParameterDefinition:
    """Metadata required to present and access one fixed DSP parameter."""

    parameter_id: DspParameterId
    block_id: DspBlockId
    name: str
    byte_count: int
    flags: DspParameterFlag = DspParameterFlag.NONE

    @property
    def writable(self) -> bool:
        """Return whether the fixed contract permits writes."""
        return bool(self.flags & DspParameterFlag.WRITABLE)

    def accepts(self, data: bytes) -> bool:
        """Return whether opaque bytes satisfy the fixed write contract.

        Args:
            data: Complete uninterpreted parameter contents.

        Returns:
            ``True`` when the value may be written to the parameter.
        """
        return bool(
            self.writable
            and isinstance(data, bytes)
            and len(data) == self.byte_count
        )


DSP_BLOCKS = (
    DspBlockDefinition(DspBlockId.ADC_SELECT, "ADC Select"),
    DspBlockDefinition(DspBlockId.SOURCE_SELECT, "Source Select"),
    DspBlockDefinition(DspBlockId.BAND_1_COMPRESSOR, "Band 1 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_2_COMPRESSOR, "Band 2 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_3_COMPRESSOR, "Band 3 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_4_COMPRESSOR, "Band 4 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_5_COMPRESSOR, "Band 5 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_6_COMPRESSOR, "Band 6 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_7_COMPRESSOR, "Band 7 Compressor"),
    DspBlockDefinition(DspBlockId.BAND_8_COMPRESSOR, "Band 8 Compressor"),
    DspBlockDefinition(DspBlockId.PHASE_COMP_GAIN_1, "Phase Comp Gain 1"),
    DspBlockDefinition(DspBlockId.PHASE_COMP_GAIN_2, "Phase Comp Gain 2"),
    DspBlockDefinition(DspBlockId.PHASE_COMP_GAIN_3, "Phase Comp Gain 3"),
    DspBlockDefinition(DspBlockId.OUTPUT_HEADROOM, "Output Headroom"),
    DspBlockDefinition(DspBlockId.SOFT_CLIP, "Soft Clip"),
)

DSP_PARAMETERS = (
    DspParameterDefinition(
        DspParameterId.ADC_SELECT,
        DspBlockId.ADC_SELECT,
        "Selection",
        4,
        DspParameterFlag.WRITABLE,
    ),
    DspParameterDefinition(
        DspParameterId.SOURCE_SELECT,
        DspBlockId.SOURCE_SELECT,
        "Selection",
        4,
        DspParameterFlag.WRITABLE,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_1_COMPRESSOR_LUT,
        DspBlockId.BAND_1_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_2_COMPRESSOR_LUT,
        DspBlockId.BAND_2_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_3_COMPRESSOR_LUT,
        DspBlockId.BAND_3_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_4_COMPRESSOR_LUT,
        DspBlockId.BAND_4_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_5_COMPRESSOR_LUT,
        DspBlockId.BAND_5_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_6_COMPRESSOR_LUT,
        DspBlockId.BAND_6_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_7_COMPRESSOR_LUT,
        DspBlockId.BAND_7_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_8_COMPRESSOR_LUT,
        DspBlockId.BAND_8_COMPRESSOR,
        "LUT",
        136,
    ),
    DspParameterDefinition(
        DspParameterId.PHASE_COMP_GAIN_1,
        DspBlockId.PHASE_COMP_GAIN_1,
        "Gain",
        4,
        DspParameterFlag.WRITABLE,
    ),
    DspParameterDefinition(
        DspParameterId.PHASE_COMP_GAIN_2,
        DspBlockId.PHASE_COMP_GAIN_2,
        "Gain",
        4,
        DspParameterFlag.WRITABLE,
    ),
    DspParameterDefinition(
        DspParameterId.PHASE_COMP_GAIN_3,
        DspBlockId.PHASE_COMP_GAIN_3,
        "Gain",
        4,
        DspParameterFlag.WRITABLE,
    ),
    DspParameterDefinition(
        DspParameterId.OUTPUT_HEADROOM_GAIN,
        DspBlockId.OUTPUT_HEADROOM,
        "Gain",
        4,
        DspParameterFlag.WRITABLE,
    ),
    DspParameterDefinition(
        DspParameterId.SOFT_CLIP_LUT,
        DspBlockId.SOFT_CLIP,
        "LUT",
        180,
    ),
)

DSP_BLOCKS_BY_ID = {definition.block_id: definition for definition in DSP_BLOCKS}
DSP_PARAMETERS_BY_ID = {
    definition.parameter_id: definition for definition in DSP_PARAMETERS
}
