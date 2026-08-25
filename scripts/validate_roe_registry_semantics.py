"""Validate canonical ROE registry semantics against frozen real-data lineage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend.amr.financial_factor_registry import (
    ROE_TTM_ENDING_EQUITY,
    financial_factor_registry,
)

ART = PROJECT / "artifacts"
PROV = PROJECT / "docs" / "provenance"
OUT = ART / "roe_registry_semantics"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    definition = ROE_TTM_ENDING_EQUITY
    authority = pd.read_parquet(
        ART / "authoritative_financial_snapshot" / "processed" / "authoritative_factor_rows.parquet"
    )
    dependencies = pd.read_parquet(
        ART / "authoritative_financial_snapshot" / "lineage" / "factor_dependency_lineage.parquet"
    )
    p05_lineage = pd.read_parquet(ART / "p05_candidate_handoff" / "p05_lineage.parquet")
    c_amendment = load(PROV / "C_RECEIVE_SCOPE_AMENDMENT.json")
    chapter6 = load(PROV / "CHAPTER_6_BP_SCOPE_EXTENSION_AMENDMENT.json")

    roe = authority.loc[authority["factor_id"].eq(definition.machine_factor_id)].copy()
    roe_dependency = dependencies.loc[
        dependencies["factor_id"].eq(definition.machine_factor_id)
    ].copy()
    p05_roe = p05_lineage.loc[p05_lineage["factor_id"].eq(definition.machine_factor_id)].copy()
    numerator = pd.to_numeric(roe[definition.numerator_source], errors="coerce")
    denominator = pd.to_numeric(roe[definition.denominator_source], errors="coerce")
    expected = numerator / denominator.where(denominator != 0)

    accepted = c_amendment["clarified_acceptance_scope"]["accepted_factors"]
    accepted_roe = next(item for item in accepted if item["factor_id"] == "ROE")

    checks = {
        "REGISTRY_MACHINE_ID_PASS": definition.machine_factor_id == "ROE",
        "REGISTRY_CANONICAL_NAME_PASS": (
            definition.canonical_semantic_name == "ROE_TTM_ENDING_EQUITY"
        ),
        "REGISTRY_FORMULA_VERSION_PASS": (
            definition.formula_id == "FORMULA_ROE_TTM_ENDING_EQUITY"
            and definition.formula_version == 1
            and definition.formula_reference == "FORMULA_ROE_TTM_ENDING_EQUITY_V1"
        ),
        "REGISTRY_ALIAS_RESOLUTION_PASS": all(
            financial_factor_registry.resolve(identifier) is definition
            for identifier in (
                "ROE",
                "ROE_TTM_ENDING_EQUITY",
                "ROE_TTM_PARENT_ENDING_EQUITY",
                "FORMULA_ROE_TTM_ENDING_EQUITY_V1",
            )
        ),
        "PROVIDER_FIELD_NON_EQUIVALENCE_PASS": all(
            financial_factor_registry.get(identifier) is None
            for identifier in (
                "return_on_equity_ttm",
                "return_on_equity_weighted_average",
                "roe_diluted",
            )
        ),
        "FROZEN_AUTHORITY_SCOPE_PASS": len(roe) == 90,
        "FROZEN_AUTHORITY_FORMULA_REFERENCE_PASS": (
            set(roe["formula_reference"]) == {definition.formula_reference}
        ),
        "FROZEN_AUTHORITY_VALUE_PASS": (
            np.isfinite(expected).all()
            and np.allclose(
                roe["raw_factor_value"].to_numpy(dtype=float),
                expected.to_numpy(dtype=float),
                rtol=0.0,
                atol=1e-12,
            )
        ),
        "FROZEN_DEPENDENCY_LINEAGE_PASS": (
            len(roe_dependency) == 1
            and roe_dependency.iloc[0]["formula_reference"] == definition.formula_reference
            and roe_dependency.iloc[0]["formula"] == definition.formula
            and roe_dependency.iloc[0]["numerator_source"] == definition.numerator_source
            and roe_dependency.iloc[0]["denominator_source"] == definition.denominator_source
        ),
        "P05_LINEAGE_PASS": (
            len(p05_roe) == 90
            and set(p05_roe["formula_reference"]) == {definition.formula_reference}
        ),
        "ACCEPTANCE_SEMANTIC_NAME_PASS": (
            accepted_roe["accepted_semantic_name"] == definition.canonical_semantic_name
            and chapter6["expanded_acceptance_scope"]["semantic_factors"][0]
            == definition.canonical_semantic_name
        ),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    passed = all(checks.values())
    result = {
        "task_id": "ROE-REGISTRY-SEMANTIC-UNIFICATION",
        "status": "ROE_REGISTRY_SEMANTICS_VALIDATED" if passed else "BLOCKED_BY_ROE_REGISTRY_MISMATCH",
        "canonical_definition": {
            "machine_factor_id": definition.machine_factor_id,
            "canonical_semantic_name": definition.canonical_semantic_name,
            "formula_id": definition.formula_id,
            "formula_version": definition.formula_version,
            "formula_reference": definition.formula_reference,
            "formula": definition.formula,
            "numerator_source": definition.numerator_source,
            "denominator_source": definition.denominator_source,
            "accounting_scope": definition.accounting_scope,
            "period_semantics": definition.period_semantics,
        },
        "frozen_rows_validated": len(roe),
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_failed": len(checks) - sum(checks.values()),
        "failed_checks": [name for name, value in checks.items() if not value],
        "frozen_data_rewritten": False,
        "rqdata_query_performed": False,
        "production_ready": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ROE_REGISTRY_SEMANTICS_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
