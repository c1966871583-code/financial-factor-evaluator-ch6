"""Canonical metadata registry for governed financial-factor semantics.

The registry is metadata-only: formulas are descriptive strings and are never
evaluated.  Machine IDs remain stable for storage compatibility while semantic
names and formula versions are resolved through one fail-closed definition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _normalize(value: str) -> str:
    return re.sub(r"[_\s]+", "_", value.strip().upper())


@dataclass(frozen=True)
class FinancialFactorDefinition:
    machine_factor_id: str
    canonical_semantic_name: str
    formula_id: str
    formula_version: int
    formula: str
    numerator_source: str
    denominator_source: str
    accounting_scope: str
    period_semantics: str
    aliases: tuple[str, ...] = ()

    @property
    def formula_reference(self) -> str:
        return f"{self.formula_id}_V{self.formula_version}"


class FinancialFactorRegistry:
    def __init__(self, definitions: tuple[FinancialFactorDefinition, ...]) -> None:
        self._by_machine_id: dict[str, FinancialFactorDefinition] = {}
        self._by_identifier: dict[str, FinancialFactorDefinition] = {}
        for definition in definitions:
            machine_id = _normalize(definition.machine_factor_id)
            if machine_id in self._by_machine_id:
                raise ValueError(f"Duplicate financial factor ID: {machine_id}")
            self._by_machine_id[machine_id] = definition
            identifiers = (
                definition.machine_factor_id,
                definition.canonical_semantic_name,
                definition.formula_reference,
                *definition.aliases,
            )
            for identifier in identifiers:
                normalized = _normalize(identifier)
                existing = self._by_identifier.get(normalized)
                if existing is not None and existing is not definition:
                    raise ValueError(f"Financial factor alias collision: {identifier}")
                self._by_identifier[normalized] = definition

    def resolve(self, identifier: str) -> FinancialFactorDefinition:
        definition = self._by_identifier.get(_normalize(identifier))
        if definition is None:
            raise ValueError(f"Unknown financial factor identifier: {identifier!r}")
        return definition

    def get(self, identifier: str) -> FinancialFactorDefinition | None:
        try:
            return self.resolve(identifier)
        except ValueError:
            return None


ROE_TTM_ENDING_EQUITY = FinancialFactorDefinition(
    machine_factor_id="ROE",
    canonical_semantic_name="ROE_TTM_ENDING_EQUITY",
    formula_id="FORMULA_ROE_TTM_ENDING_EQUITY",
    formula_version=1,
    formula="np_parent_company_ownersTTM / equity_parent_company",
    numerator_source="np_parent_company_ownersTTM",
    denominator_source="equity_parent_company",
    accounting_scope="consolidated attributable parent profit / ending parent equity",
    period_semantics="TTM numerator; report-period-end denominator",
    aliases=(
        "ROE_TTM_PARENT_ENDING_EQUITY",
        "RETURN_ON_EQUITY_TTM_ENDING_EQUITY",
    ),
)


financial_factor_registry = FinancialFactorRegistry((ROE_TTM_ENDING_EQUITY,))
