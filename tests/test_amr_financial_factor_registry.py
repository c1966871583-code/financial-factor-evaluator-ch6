import pytest

from backend.amr.financial_factor_registry import (
    ROE_TTM_ENDING_EQUITY,
    financial_factor_registry,
)


def test_roe_machine_id_and_semantic_name_resolve_to_one_definition():
    by_id = financial_factor_registry.resolve("ROE")
    by_name = financial_factor_registry.resolve("roe_ttm_ending_equity")
    assert by_id is by_name is ROE_TTM_ENDING_EQUITY


def test_roe_compatibility_alias_resolves_without_changing_canonical_name():
    definition = financial_factor_registry.resolve("ROE_TTM_PARENT_ENDING_EQUITY")
    assert definition.canonical_semantic_name == "ROE_TTM_ENDING_EQUITY"


def test_roe_formula_identity_is_versioned_and_exact():
    definition = ROE_TTM_ENDING_EQUITY
    assert definition.formula_id == "FORMULA_ROE_TTM_ENDING_EQUITY"
    assert definition.formula_version == 1
    assert definition.formula_reference == "FORMULA_ROE_TTM_ENDING_EQUITY_V1"
    assert definition.formula == "np_parent_company_ownersTTM / equity_parent_company"


def test_formula_reference_resolves_to_same_definition():
    assert (
        financial_factor_registry.resolve("FORMULA_ROE_TTM_ENDING_EQUITY_V1")
        is ROE_TTM_ENDING_EQUITY
    )


def test_registry_is_metadata_only_and_fail_closed():
    assert not hasattr(ROE_TTM_ENDING_EQUITY, "callable")
    with pytest.raises(ValueError, match="Unknown financial factor identifier"):
        financial_factor_registry.resolve("ROE_WEIGHTED_AVERAGE")


@pytest.mark.parametrize(
    "provider_field",
    ["return_on_equity_ttm", "return_on_equity_weighted_average", "roe_diluted"],
)
def test_provider_roe_fields_are_not_formula_equivalence_aliases(provider_field):
    with pytest.raises(ValueError, match="Unknown financial factor identifier"):
        financial_factor_registry.resolve(provider_field)
