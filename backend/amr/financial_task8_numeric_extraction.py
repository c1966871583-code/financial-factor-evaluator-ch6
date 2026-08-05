"""FIN-HO-8-B2: extract already-approved Task 8 numeric candidate rows.

This boundary validates and carries supplied raw/evaluation values.  It never
constructs a combination, transforms values, invokes an evaluator, or ranks
candidates.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import pandas as pd

from .financial_p3_combinations import get_fin24_combination_definitions
from .financial_p3_info_gain_contract import build_financial_p3_info_gain_contract
from .financial_task8_semantics import serialize_financial_task8_value_semantics


TASK8_NUMERIC_EXTRACTION_VERSION = "FinancialTask8NumericExtraction-v1.0"
TASK8_NUMERIC_COLUMNS = (
    "evaluation_date", "code", "factor_id", "raw_pit_factor_value",
    "evaluation_factor_value", "effective_date", "source_record_id",
    "source_content_hash",
)
_FORBIDDEN_COLUMNS = {
    "neutralized_value", "selected_candidate", "best_candidate",
    "selection_score", "information_gain_decision", "admission_decision",
}


@dataclass(frozen=True)
class ApprovedNumericCandidateBatch:
    candidate_id: str
    candidate_definition_hash: str
    declared_sample_fingerprint: str
    _rows: pd.DataFrame
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self._rows, pd.DataFrame):
            raise TypeError("_rows must be a pandas DataFrame")
        object.__setattr__(self, "_rows", self._rows.copy(deep=True))
        object.__setattr__(self, "provenance", MappingProxyType(copy.deepcopy(dict(self.provenance))))

    def get_rows(self) -> pd.DataFrame:
        return self._rows.copy(deep=True)


@dataclass(frozen=True)
class Task8NumericCandidateExtraction:
    candidate_id: str
    candidate_definition_hash: str
    sample_fingerprint: str
    row_count: int
    period_count: int
    records_fingerprint: str
    rows: tuple[dict[str, object], ...]
    production_status: str = "not production ready"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Task8NumericExtractionResult:
    schema_version: str
    semantic_policy_content_hash: str
    extractions: tuple[Task8NumericCandidateExtraction, ...]
    content_hash: str
    production_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_financial_task8_approved_numeric_datasets(
    batches: Sequence[ApprovedNumericCandidateBatch],
) -> Task8NumericExtractionResult:
    """Validate the approved fixed samples and return deterministic copies."""
    if not isinstance(batches, Sequence) or isinstance(batches, (str, bytes)):
        raise TypeError("batches must be a sequence of ApprovedNumericCandidateBatch")
    definitions = {item.combination_id: item for item in get_fin24_combination_definitions()}
    contract = build_financial_p3_info_gain_contract()
    samples = {item.combo_id: item for item in contract.common_sample_references}
    expected_ids = tuple(item.combo_id for item in contract.combination_references)
    received_ids = tuple(item.candidate_id for item in batches)
    if received_ids != expected_ids:
        raise ValueError("candidate order and set must be exactly VQ, QG, CASHQ")
    extractions = []
    for batch in batches:
        if not isinstance(batch, ApprovedNumericCandidateBatch):
            raise TypeError("each batch must be ApprovedNumericCandidateBatch")
        candidate_id = batch.candidate_id
        definition = definitions[candidate_id]
        sample = samples[candidate_id]
        if batch.candidate_definition_hash != definition.content_hash:
            raise ValueError(f"{candidate_id}: candidate definition hash drift")
        if batch.declared_sample_fingerprint != sample.common_sample_fingerprint:
            raise ValueError(f"{candidate_id}: declared sample fingerprint drift")
        if dict(batch.provenance) != {
            "approved_dataset": "frozen_synthetic_common_sample",
            "synthetic_test_only": True,
        }:
            raise ValueError(f"{candidate_id}: provenance is not the approved dataset")
        rows = _validate_rows(batch.get_rows(), candidate_id=candidate_id)
        if len(rows) != 900 or rows["evaluation_date"].nunique() != 18:
            raise ValueError(f"{candidate_id}: requires exactly 18 periods and 900 rows")
        records = _records(rows)
        records_fingerprint = _hash(records)
        extractions.append(Task8NumericCandidateExtraction(
            candidate_id=candidate_id,
            candidate_definition_hash=definition.content_hash,
            sample_fingerprint=sample.common_sample_fingerprint,
            row_count=len(records), period_count=18,
            records_fingerprint=records_fingerprint, rows=tuple(records),
        ))
    semantic_hash = json.loads(serialize_financial_task8_value_semantics())["content_hash"]
    payload = {
        "schema_version": TASK8_NUMERIC_EXTRACTION_VERSION,
        "semantic_policy_content_hash": semantic_hash,
        "extractions": [item.to_dict() for item in extractions],
        "production_status": "not production ready",
    }
    return Task8NumericExtractionResult(
        schema_version=TASK8_NUMERIC_EXTRACTION_VERSION,
        semantic_policy_content_hash=semantic_hash,
        extractions=tuple(extractions),
        content_hash=_hash(payload),
        production_status="not production ready",
    )


def serialize_financial_task8_numeric_extraction(
    result: Task8NumericExtractionResult,
) -> str:
    if not isinstance(result, Task8NumericExtractionResult):
        raise TypeError("result must be Task8NumericExtractionResult")
    return json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))


def _validate_rows(rows: pd.DataFrame, *, candidate_id: str) -> pd.DataFrame:
    forbidden = _FORBIDDEN_COLUMNS & set(rows.columns)
    if forbidden:
        raise ValueError("forbidden numeric-extraction columns: " + ",".join(sorted(forbidden)))
    if tuple(rows.columns) != TASK8_NUMERIC_COLUMNS:
        raise ValueError("rows must have the exact frozen numeric columns")
    normalized = rows.copy(deep=True)
    for column in ("evaluation_date", "effective_date"):
        normalized[column] = pd.to_datetime(normalized[column], errors="coerce")
        if normalized[column].isna().any():
            raise ValueError(f"invalid {column}")
        normalized[column] = normalized[column].dt.date.astype(str)
    for column in ("code", "factor_id", "source_record_id", "source_content_hash"):
        if normalized[column].isna().any() or (normalized[column].astype(str).str.len() == 0).any():
            raise ValueError(f"invalid {column}")
        normalized[column] = normalized[column].astype(str)
    if not (normalized["factor_id"] == candidate_id).all():
        raise ValueError("factor_id must equal its candidate_id")
    if normalized.duplicated(["evaluation_date", "code", "factor_id"]).any():
        raise ValueError("duplicate Task 8 sample key")
    for column in ("raw_pit_factor_value", "evaluation_factor_value"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        if normalized[column].isna().any() or not normalized[column].map(math.isfinite).all():
            raise ValueError(f"non-finite {column}")
    if (pd.to_datetime(normalized["effective_date"]) > pd.to_datetime(normalized["evaluation_date"])).any():
        raise ValueError("PIT violation: effective_date after evaluation_date")
    if not normalized["source_content_hash"].map(_is_sha256).all():
        raise ValueError("source_content_hash must be SHA-256")
    return normalized.sort_values(["evaluation_date", "code", "factor_id"], kind="stable").reset_index(drop=True)


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {column: _json_value(row[column]) for column in TASK8_NUMERIC_COLUMNS}
        for _, row in frame.iterrows()
    ]


def _json_value(value: object) -> object:
    return float(value) if isinstance(value, float) else value


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
