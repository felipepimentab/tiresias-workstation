"""Define the fixed MVP DSP block and parameter contract.

This module is the workstation-owned mirror of the firmware contract. The
numeric identifiers and parameter metadata must remain synchronized with
``src/codec/dsp_parameter_catalog.h`` in the firmware repository.
"""

from dataclasses import dataclass
from enum import IntEnum, IntFlag


DSP_PARAMETER_CONTRACT_CRC32 = 0xF62C1808


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
    """Opt-in properties for an otherwise read-only Q5.23 parameter."""

    NONE = 0
    WRITABLE = 1 << 0
    INTEGER = 1 << 1


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
    word_count: int
    flags: DspParameterFlag = DspParameterFlag.NONE
    minimum: int | None = None
    maximum: int | None = None
    default: int | None = None
    step: int | None = None

    @property
    def writable(self) -> bool:
        """Return whether the fixed contract permits writes."""
        return bool(self.flags & DspParameterFlag.WRITABLE)

    @property
    def integer(self) -> bool:
        """Return whether words use signed integer rather than Q5.23 encoding."""
        return bool(self.flags & DspParameterFlag.INTEGER)

    def accepts(self, value: int) -> bool:
        """Return whether a scalar value satisfies the fixed write contract.

        Args:
            value: Encoded signed 32-bit parameter value.

        Returns:
            ``True`` when the value may be written to the parameter.
        """
        return bool(
            self.writable
            and self.word_count == 1
            and self.minimum is not None
            and self.maximum is not None
            and self.step is not None
            and self.minimum <= value <= self.maximum
            and self.step > 0
            and (value - self.minimum) % self.step == 0
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
        1,
        DspParameterFlag.WRITABLE | DspParameterFlag.INTEGER,
        0,
        3,
        0,
        1,
    ),
    DspParameterDefinition(
        DspParameterId.SOURCE_SELECT,
        DspBlockId.SOURCE_SELECT,
        "Selection",
        1,
        DspParameterFlag.WRITABLE | DspParameterFlag.INTEGER,
        0,
        1,
        1,
        1,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_1_COMPRESSOR_LUT,
        DspBlockId.BAND_1_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_2_COMPRESSOR_LUT,
        DspBlockId.BAND_2_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_3_COMPRESSOR_LUT,
        DspBlockId.BAND_3_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_4_COMPRESSOR_LUT,
        DspBlockId.BAND_4_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_5_COMPRESSOR_LUT,
        DspBlockId.BAND_5_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_6_COMPRESSOR_LUT,
        DspBlockId.BAND_6_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_7_COMPRESSOR_LUT,
        DspBlockId.BAND_7_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.BAND_8_COMPRESSOR_LUT,
        DspBlockId.BAND_8_COMPRESSOR,
        "LUT",
        34,
    ),
    DspParameterDefinition(
        DspParameterId.PHASE_COMP_GAIN_1,
        DspBlockId.PHASE_COMP_GAIN_1,
        "Gain",
        1,
        DspParameterFlag.WRITABLE,
        0,
        0x02000000,
        0x00800000,
        0x00008000,
    ),
    DspParameterDefinition(
        DspParameterId.PHASE_COMP_GAIN_2,
        DspBlockId.PHASE_COMP_GAIN_2,
        "Gain",
        1,
        DspParameterFlag.WRITABLE,
        0,
        0x02000000,
        0x00800000,
        0x00008000,
    ),
    DspParameterDefinition(
        DspParameterId.PHASE_COMP_GAIN_3,
        DspBlockId.PHASE_COMP_GAIN_3,
        "Gain",
        1,
        DspParameterFlag.WRITABLE,
        0,
        0x02000000,
        0x00800000,
        0x00008000,
    ),
    DspParameterDefinition(
        DspParameterId.OUTPUT_HEADROOM_GAIN,
        DspBlockId.OUTPUT_HEADROOM,
        "Gain",
        1,
        DspParameterFlag.WRITABLE,
        0,
        0x02000000,
        0x00800000,
        0x00008000,
    ),
    DspParameterDefinition(
        DspParameterId.SOFT_CLIP_LUT,
        DspBlockId.SOFT_CLIP,
        "LUT",
        45,
    ),
)

DSP_BLOCKS_BY_ID = {definition.block_id: definition for definition in DSP_BLOCKS}
DSP_PARAMETERS_BY_ID = {
    definition.parameter_id: definition for definition in DSP_PARAMETERS
}
