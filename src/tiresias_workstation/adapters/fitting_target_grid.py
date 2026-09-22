"""Define the shared CEC1 fitting grid used by board-target rule adapters."""

FILTERBANK_CENTRES_HZ = (
    177.0, 297.0, 500.0, 841.0, 1414.0, 2378.0, 4000.0, 6727.0, 11314.0,
)
FILTERBANK_EDGES_HZ = (
    0.0, 229.2793, 385.357, 648.4597, 1090.5, 1833.7, 3084.2,
    5187.3, 8724.1, 22050.0,
)
INPUT_LEVELS_DB_SPL = tuple(float(level) for level in range(-10, 111))
