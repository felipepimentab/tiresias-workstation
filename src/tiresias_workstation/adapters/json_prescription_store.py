"""Persist complete generated-prescription artifacts as inspectable JSON files."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import re
from typing import Any

from tiresias_workstation.domain.dsp_contract import DspParameterId
from tiresias_workstation.domain.fittings import (
    Audiogram,
    DspMapping,
    GeneratedPrescription,
    PrescriptionRuleMetadata,
    PrescriptionTarget,
)
from tiresias_workstation.domain.prescriptions import (
    Prescription,
    PrescriptionParameter,
    PrescriptionSource,
)


ARTIFACT_FORMAT = "tiresias-generated-prescription"
ARTIFACT_VERSION = 1
_VALID_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_LOGGER = logging.getLogger(__name__)


def audiogram_to_dict(audiogram: Audiogram) -> dict[str, Any]:
    """Convert an audiogram to its portable JSON representation."""
    return {
        "frequencies_hz": list(audiogram.frequencies_hz),
        "left_levels_db_hl": list(audiogram.left_levels_db_hl),
        "right_levels_db_hl": list(audiogram.right_levels_db_hl),
    }


def target_to_dict(target: PrescriptionTarget) -> dict[str, Any]:
    """Convert an exact prescription target to inspectable JSON data."""
    return {
        "rule": asdict(target.rule),
        "audiogram": audiogram_to_dict(target.audiogram),
        "filterbank": {
            "band_centres_hz": list(target.band_centres_hz),
            "band_edges_hz": list(target.band_edges_hz),
        },
        "dynamics": {
            "input_levels_db_spl": list(target.input_levels_db_spl),
            "left_gain_db_by_band": [
                list(row) for row in target.left_gain_db_by_band
            ],
            "right_gain_db_by_band": [
                list(row) for row in target.right_gain_db_by_band
            ],
            "attack_time_ms": target.attack_time_ms,
            "release_time_ms": target.release_time_ms,
            "rms_level_time_constant_ms": target.rms_level_time_constant_ms,
        },
        "endpoint_policy": target.endpoint_policy,
    }


def mapping_to_dict(mapping: DspMapping) -> dict[str, Any]:
    """Convert calibrated DSP conversion details to JSON data."""
    return {
        "calibration_id": mapping.calibration_id,
        "selected_ear": mapping.ear,
        "detector_points_dbfs": list(mapping.detector_points_dbfs),
        "mapped_input_levels_db_spl_by_band": [
            list(row) for row in mapping.mapped_input_levels_db_spl_by_band
        ],
        "desired_gain_db_by_band": [
            list(row) for row in mapping.desired_gain_db_by_band
        ],
        "lut_gain_db_by_band": [
            list(row) for row in mapping.lut_gain_db_by_band
        ],
        "quantized_lut_gain_db_by_band": [
            list(row) for row in mapping.quantized_lut_gain_db_by_band
        ],
        "common_bias_total_db": mapping.common_bias_total_db,
        "quantized_bias_per_stage_db": mapping.quantized_bias_per_stage_db,
    }


def prescription_to_dict(prescription: Prescription) -> dict[str, Any]:
    """Convert transport-ready DSP values to portable hexadecimal JSON data."""
    return {
        "profile_id": prescription.profile_id,
        "display_name": prescription.display_name,
        "description": prescription.description,
        "format_name": prescription.format_name,
        "format_version": prescription.format_version,
        "sha256": prescription.sha256,
        "payload_byte_count": prescription.payload_byte_count,
        "source": asdict(prescription.source),
        "parameters": [
            {
                "parameter_id": int(parameter.parameter_id),
                "data_hex": parameter.data.hex(),
            }
            for parameter in prescription.parameters
        ],
    }


def artifact_to_dict(artifact: GeneratedPrescription) -> dict[str, Any]:
    """Convert all generation stages to the versioned artifact envelope."""
    return {
        "format": ARTIFACT_FORMAT,
        "version": ARTIFACT_VERSION,
        "artifact_id": artifact.artifact_id,
        "name": artifact.name,
        "created_at": artifact.created_at,
        "audiogram": audiogram_to_dict(artifact.target.audiogram),
        "prescription_target": target_to_dict(artifact.target),
        "dsp_mapping": mapping_to_dict(artifact.mapping),
        "dsp_parameters": prescription_to_dict(artifact.prescription),
    }


def artifact_from_dict(value: dict[str, Any]) -> GeneratedPrescription:
    """Validate and rebuild a generated prescription from JSON data.

    Args:
        value: Parsed artifact envelope.

    Returns:
        Validated domain artifact.  Constructing the nested prescription also
        verifies its canonical SHA-256 digest and DSP parameter sizes.

    Raises:
        ValueError: If the format identity or version is unsupported.
        KeyError: If a required field is absent.
        TypeError: If nested data has an incompatible type.
    """
    if value.get("format") != ARTIFACT_FORMAT:
        raise ValueError("Unsupported generated-prescription format.")
    if value.get("version") != ARTIFACT_VERSION:
        raise ValueError("Unsupported generated-prescription version.")

    target_value = value["prescription_target"]
    audiogram_value = target_value["audiogram"]
    audiogram = Audiogram(
        frequencies_hz=_float_tuple(audiogram_value["frequencies_hz"]),
        left_levels_db_hl=_float_tuple(audiogram_value["left_levels_db_hl"]),
        right_levels_db_hl=_float_tuple(audiogram_value["right_levels_db_hl"]),
    )
    rule_value = target_value["rule"]
    rule = PrescriptionRuleMetadata(
        rule_id=str(rule_value["rule_id"]),
        display_name=str(rule_value["display_name"]),
        version=str(rule_value["version"]),
        source=str(rule_value["source"]),
    )
    filterbank = target_value["filterbank"]
    dynamics = target_value["dynamics"]
    target = PrescriptionTarget(
        rule=rule,
        audiogram=audiogram,
        band_centres_hz=_float_tuple(filterbank["band_centres_hz"]),
        band_edges_hz=_float_tuple(filterbank["band_edges_hz"]),
        input_levels_db_spl=_float_tuple(dynamics["input_levels_db_spl"]),
        left_gain_db_by_band=_float_matrix(dynamics["left_gain_db_by_band"]),
        right_gain_db_by_band=_float_matrix(dynamics["right_gain_db_by_band"]),
        attack_time_ms=float(dynamics["attack_time_ms"]),
        release_time_ms=float(dynamics["release_time_ms"]),
        rms_level_time_constant_ms=float(
            dynamics["rms_level_time_constant_ms"]
        ),
        endpoint_policy=str(target_value["endpoint_policy"]),
    )

    mapping_value = value["dsp_mapping"]
    selected_ear = str(mapping_value["selected_ear"])
    if selected_ear not in ("left", "right"):
        raise ValueError("DSP mapping selected ear must be left or right.")
    mapping = DspMapping(
        calibration_id=str(mapping_value["calibration_id"]),
        ear=selected_ear,
        detector_points_dbfs=_float_tuple(
            mapping_value["detector_points_dbfs"]
        ),
        mapped_input_levels_db_spl_by_band=_float_matrix(
            mapping_value["mapped_input_levels_db_spl_by_band"]
        ),
        desired_gain_db_by_band=_float_matrix(
            mapping_value["desired_gain_db_by_band"]
        ),
        lut_gain_db_by_band=_float_matrix(
            mapping_value["lut_gain_db_by_band"]
        ),
        quantized_lut_gain_db_by_band=_float_matrix(
            mapping_value["quantized_lut_gain_db_by_band"]
        ),
        common_bias_total_db=float(mapping_value["common_bias_total_db"]),
        quantized_bias_per_stage_db=float(
            mapping_value["quantized_bias_per_stage_db"]
        ),
    )

    prescription_value = value["dsp_parameters"]
    source_value = prescription_value["source"]
    parameters = tuple(
        PrescriptionParameter(
            DspParameterId(int(parameter["parameter_id"])),
            bytes.fromhex(str(parameter["data_hex"])),
        )
        for parameter in prescription_value["parameters"]
    )
    prescription = Prescription(
        profile_id=str(prescription_value["profile_id"]),
        display_name=str(prescription_value["display_name"]),
        description=str(prescription_value["description"]),
        format_name=str(prescription_value["format_name"]),
        format_version=int(prescription_value["format_version"]),
        parameters=parameters,
        expected_sha256=str(prescription_value["sha256"]),
        source=PrescriptionSource(
            repository=str(source_value["repository"]),
            path=str(source_value["path"]),
            revision=str(source_value["revision"]),
            sha256=str(source_value["sha256"]),
        ),
    )
    if int(prescription_value["payload_byte_count"]) != prescription.payload_byte_count:
        raise ValueError("Stored DSP payload byte count does not match its parameters.")
    artifact_id = str(value["artifact_id"])
    if prescription.profile_id != artifact_id:
        raise ValueError("Artifact and DSP prescription identifiers do not match.")
    if audiogram_to_dict(audiogram) != value["audiogram"]:
        raise ValueError("Top-level and target audiograms do not match.")
    return GeneratedPrescription(
        artifact_id=artifact_id,
        name=str(value["name"]),
        created_at=str(value["created_at"]),
        target=target,
        mapping=mapping,
        prescription=prescription,
    )


class JsonPrescriptionStore:
    """Store each complete generated prescription in one atomic JSON file."""

    def __init__(self, directory: Path) -> None:
        """Configure the local artifact directory.

        Args:
            directory: Application-owned directory for generated JSON files.
        """
        self.directory = directory

    def save(self, artifact: GeneratedPrescription) -> None:
        """Atomically create or replace one generated artifact."""
        path = self._path(artifact.artifact_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(
                artifact_to_dict(artifact),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def list(self) -> tuple[GeneratedPrescription, ...]:
        """Return valid saved artifacts ordered by name then identifier."""
        if not self.directory.exists():
            return ()
        artifacts: list[GeneratedPrescription] = []
        for path in self.directory.glob("*.json"):
            if not path.is_file():
                continue
            try:
                artifact = self._read(path)
                if self._path(artifact.artifact_id) != path:
                    raise ValueError("Artifact identifier must match its filename.")
                artifacts.append(artifact)
            except (KeyError, OSError, TypeError, ValueError):
                # One damaged user file must not prevent the workstation from
                # starting or make every other saved prescription unavailable.
                _LOGGER.warning(
                    "Ignoring invalid generated prescription %s",
                    path,
                    exc_info=True,
                )
        return tuple(
            sorted(
                artifacts,
                key=lambda artifact: (
                    artifact.name.casefold(),
                    artifact.artifact_id,
                ),
            )
        )

    def get(self, artifact_id: str) -> GeneratedPrescription:
        """Return one saved artifact by stable identifier."""
        path = self._path(artifact_id)
        if not path.is_file():
            raise KeyError(artifact_id)
        artifact = self._read(path)
        if artifact.artifact_id != artifact_id:
            raise ValueError("Artifact identifier must match its filename.")
        return artifact

    def delete(self, artifact_id: str) -> None:
        """Delete one saved artifact without affecting bundled profiles."""
        path = self._path(artifact_id)
        if not path.is_file():
            raise KeyError(artifact_id)
        path.unlink()

    @staticmethod
    def export(artifact: GeneratedPrescription, path: Path) -> None:
        """Write a portable copy without changing the local catalog."""
        path.write_text(
            json.dumps(artifact_to_dict(artifact), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    def _path(self, artifact_id: str) -> Path:
        """Resolve a validated identifier without permitting path traversal."""
        if not _VALID_ARTIFACT_ID.fullmatch(artifact_id):
            raise ValueError("Invalid generated-prescription identifier.")
        return self.directory / f"{artifact_id}.json"

    @staticmethod
    def _read(path: Path) -> GeneratedPrescription:
        """Parse and validate one JSON artifact from disk."""
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Generated-prescription root must be an object.")
        return artifact_from_dict(value)


def _float_tuple(value: Any) -> tuple[float, ...]:
    """Normalize one JSON numeric array as an immutable tuple."""
    if not isinstance(value, list):
        raise TypeError("Expected a JSON array.")
    return tuple(float(item) for item in value)


def _float_matrix(value: Any) -> tuple[tuple[float, ...], ...]:
    """Normalize one JSON numeric matrix as immutable tuples."""
    if not isinstance(value, list):
        raise TypeError("Expected a JSON matrix.")
    return tuple(_float_tuple(row) for row in value)
