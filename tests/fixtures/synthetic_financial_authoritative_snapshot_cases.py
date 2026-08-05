"""Synthetic-only fixtures for the PRE-01 snapshot contract test."""


def valid_snapshot_rows():
    base = {
        "synthetic_test_only": True,
        "report_period": "2024-03-31", "publish_date": "2024-04-25",
        "effective_date": "2024-04-26", "evaluation_date": "2024-05-31",
        "factor_id": "ROE", "announcement_or_revision_version": "ann-v1",
        "upstream_run_id": "synthetic-run-fixed-01", "factor_sample_mask": True,
        "inclusion_or_exclusion_reason": "included", "common_sample_id": "synthetic-common-01",
        "sample_fingerprint": "synthetic-sample-fp-01", "value_variant": "raw_pit",
        "factor_direction": "higher_is_better", "preprocessing_policy_version": "synthetic-policy-v1",
        "winsorization_status": "not_applied", "standardization_status": "not_applied",
        "neutralization_status": "not_applied", "staleness_status": "fresh",
        "data_age_days": 35, "staleness_threshold_days": 120,
        "staleness_determination_basis": "evaluation_date_minus_effective_date",
        "formula_version": "roe-formula-v1", "config_version": "synthetic-config-v1",
        "code_head": "synthetic-fixed-head", "row_lineage": {"source_table": "synthetic_disclosure", "source_version": "v1"},
    }
    return [
        {**base, "code": "000001.SZ", "source_record_id": "synthetic-src-001", "factor_value": 0.12},
        {**base, "code": "000002.SZ", "source_record_id": "synthetic-src-002", "factor_value": 0.09},
    ]
