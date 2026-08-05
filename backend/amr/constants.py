"""
AMR - Autonomous Macro-Research Factor Platform
Backend constants: categories, statuses, error codes.
"""

from __future__ import annotations

# ---------------------------------------------------------------
# Factor Categories (V1.1 contract)
# ---------------------------------------------------------------
VALID_CATEGORIES = frozenset({"price_volume", "financial", "macro"})

CATEGORY_CN = {
    "price_volume": "量价因子",
    "financial": "财务因子",
    "macro": "宏观因子",
}

# ---------------------------------------------------------------
# Factor Statuses (V1.1 contract — 10 states)
# ---------------------------------------------------------------
STATUS_SUBMITTED = "submitted"
STATUS_CLASSIFIED = "classified"
STATUS_DEDUPLICATING = "deduplicating"
STATUS_DATA_CHECKING = "data_checking"
STATUS_CALCULATING = "calculating"
STATUS_VALIDATING = "validating"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REGISTERED = "registered"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

VALID_STATUSES = frozenset({
    STATUS_SUBMITTED,
    STATUS_CLASSIFIED,
    STATUS_DEDUPLICATING,
    STATUS_DATA_CHECKING,
    STATUS_CALCULATING,
    STATUS_VALIDATING,
    STATUS_PENDING_REVIEW,
    STATUS_REGISTERED,
    STATUS_REJECTED,
    STATUS_FAILED,
})

TERMINAL_STATUSES = frozenset({STATUS_REGISTERED, STATUS_REJECTED, STATUS_FAILED})

# ---------------------------------------------------------------
# Deduplication phases (V1.1 contract)
# ---------------------------------------------------------------
DEDUP_PHASE_PRECHECK = "precheck"
DEDUP_PHASE_VALUE_CHECK = "value_check"
VALID_DEDUP_PHASES = frozenset({DEDUP_PHASE_PRECHECK, DEDUP_PHASE_VALUE_CHECK})

# ---------------------------------------------------------------
# Rejection reasons (V1.2 contract)
# ---------------------------------------------------------------
REJECTION_REASON_EXACT_DUPLICATE = "exact_duplicate"
REJECTION_REASON_HIGH_SIMILARITY = "high_similarity"
REJECTION_REASON_VALIDATION_FAILED = "validation_failed"
REJECTION_REASON_MANUAL_REJECTION = "manual_rejection"
REJECTION_REASON_UNSUPPORTED_DATA = "unsupported_data"  # legacy, no longer issued

VALID_REJECTION_REASONS = frozenset({
    REJECTION_REASON_EXACT_DUPLICATE,
    REJECTION_REASON_HIGH_SIMILARITY,
    REJECTION_REASON_VALIDATION_FAILED,
    REJECTION_REASON_MANUAL_REJECTION,
    REJECTION_REASON_UNSUPPORTED_DATA,
})

# ---------------------------------------------------------------
# Blocked stages and reasons (V1.2 contract)
# ---------------------------------------------------------------
# A factor can be blocked (processing_blocked=true) at a specific stage.
# This is NOT a rejection — the factor remains classified and can be
# retried when the blocking condition is resolved.

BLOCKED_STAGE_DATA_CHECK = "data_check"
BLOCKED_STAGE_CALCULATION = "calculation"
BLOCKED_STAGE_VALIDATION = "validation"
BLOCKED_STAGE_REVIEW = "review"

VALID_BLOCKED_STAGES = frozenset({
    BLOCKED_STAGE_DATA_CHECK,
    BLOCKED_STAGE_CALCULATION,
    BLOCKED_STAGE_VALIDATION,
    BLOCKED_STAGE_REVIEW,
})

BLOCKED_REASON_DATA_UNAVAILABLE = "data_unavailable"  # legacy alias for catalog check
BLOCKED_REASON_SYSTEM_ERROR = "system_error"
BLOCKED_REASON_DATA_BINDING_REQUIRED = "data_binding_required"  # V1.3: no DatasetSnapshot bound
BLOCKED_REASON_REQUIRED_FIELD_MISSING = "required_field_missing"  # V1.3: field not in DatasetSnapshot
BLOCKED_REASON_DATA_PACKAGE_UNVERIFIED = "data_package_unverified"  # V1.3: metadata_only, no real data

VALID_BLOCKED_REASONS = frozenset({
    BLOCKED_REASON_DATA_UNAVAILABLE,
    BLOCKED_REASON_SYSTEM_ERROR,
    BLOCKED_REASON_DATA_BINDING_REQUIRED,
    BLOCKED_REASON_REQUIRED_FIELD_MISSING,
    BLOCKED_REASON_DATA_PACKAGE_UNVERIFIED,
})

# ---------------------------------------------------------------
# Error codes (V1.1 API contract)
# ---------------------------------------------------------------
ERROR_INVALID_JSON = "INVALID_JSON"
ERROR_MISSING_FIELD = "MISSING_FIELD"
ERROR_INVALID_FIELD_TYPE = "INVALID_FIELD_TYPE"
ERROR_INVALID_CATEGORY = "INVALID_CATEGORY"
ERROR_INVALID_STATUS = "INVALID_STATUS"
ERROR_INVALID_PAGINATION = "INVALID_PAGINATION"
ERROR_FACTOR_NOT_FOUND = "FACTOR_NOT_FOUND"
ERROR_DUPLICATE_SUBMISSION = "DUPLICATE_SUBMISSION"
ERROR_PRECHECK_FAILED = "PRECHECK_FAILED"
ERROR_VALUE_CHECK_FAILED = "VALUE_CHECK_FAILED"
ERROR_VALUE_CHECK_ALREADY_FINALIZED = "VALUE_CHECK_ALREADY_FINALIZED"
ERROR_COMPARISON_SET_MISMATCH = "COMPARISON_SET_MISMATCH"
ERROR_DATASET_VERSION_MISMATCH = "DATASET_VERSION_MISMATCH"
ERROR_STORE_READ_FAILED = "STORE_READ_FAILED"
ERROR_STORE_WRITE_FAILED = "STORE_WRITE_FAILED"
ERROR_PRECHECK_REQUIRED = "PRECHECK_REQUIRED"
ERROR_FACTOR_NOT_PROCESSABLE = "FACTOR_NOT_PROCESSABLE"
ERROR_DATA_CATALOG_READ_FAILED = "DATA_CATALOG_READ_FAILED"
ERROR_DATA_CHECK_FAILED = "DATA_CHECK_FAILED"
ERROR_INVALID_QUERY_PARAMETER = "INVALID_QUERY_PARAMETER"
ERROR_INTERNAL_ERROR = "INTERNAL_ERROR"
ERROR_BATCH_NOT_FOUND = "BATCH_NOT_FOUND"
ERROR_DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
ERROR_RUN_NOT_FOUND = "RUN_NOT_FOUND"
ERROR_INVALID_BATCH_DATA = "INVALID_BATCH_DATA"
ERROR_PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # V1.3: some factors succeeded, some failed

# ---------------------------------------------------------------
# Pagination defaults
# ---------------------------------------------------------------
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# ---------------------------------------------------------------
# Required submission fields
# ---------------------------------------------------------------
REQUIRED_FIELDS = {"name", "category", "formula", "data_fields"}

# ---------------------------------------------------------------
# Optional submission fields with defaults
# ---------------------------------------------------------------
OPTIONAL_FIELD_DEFAULTS = {
    "description": "",
    "code": "",
    "source_reference": "",
    "submitted_by": "",
    "frequency": "day",
    "universe": "",
    "parameters": {},
    "tags": [],
}

# ---------------------------------------------------------------
# Batch statuses (V1.3 contract)
# ---------------------------------------------------------------
BATCH_STATUS_SUBMITTED = "submitted"
BATCH_STATUS_PARTIAL_SUCCESS = "partial_success"
BATCH_STATUS_ACCEPTED = "accepted"
BATCH_STATUS_FAILED = "failed"

VALID_BATCH_STATUSES = frozenset({
    BATCH_STATUS_SUBMITTED,
    BATCH_STATUS_PARTIAL_SUCCESS,
    BATCH_STATUS_ACCEPTED,
    BATCH_STATUS_FAILED,
})

# ---------------------------------------------------------------
# Run statuses (V1.3 contract)
# ---------------------------------------------------------------
RUN_STATUS_CREATED = "created"
RUN_STATUS_VALIDATING = "validating"
RUN_STATUS_READY = "ready"
RUN_STATUS_PARTIAL_READY = "partial_ready"
RUN_STATUS_BLOCKED = "blocked"

VALID_RUN_STATUSES = frozenset({
    RUN_STATUS_CREATED,
    RUN_STATUS_VALIDATING,
    RUN_STATUS_READY,
    RUN_STATUS_PARTIAL_READY,
    RUN_STATUS_BLOCKED,
})

# ---------------------------------------------------------------
# Dataset validation statuses (V1.3 contract)
# ---------------------------------------------------------------
DATASET_VALIDATION_NOT_RUN = "not_run"
DATASET_VALIDATION_PASSED = "passed"
DATASET_VALIDATION_FAILED = "failed"

VALID_DATASET_VALIDATION_STATUSES = frozenset({
    DATASET_VALIDATION_NOT_RUN,
    DATASET_VALIDATION_PASSED,
    DATASET_VALIDATION_FAILED,
})

# ---------------------------------------------------------------
# Data domain tags (V1.3 — labels only, NOT factor categories)
# ---------------------------------------------------------------
DATA_DOMAIN_MARKET = "market"
DATA_DOMAIN_FINANCIAL = "financial"
DATA_DOMAIN_MACRO = "macro"

VALID_DATA_DOMAINS = frozenset({
    DATA_DOMAIN_MARKET,
    DATA_DOMAIN_FINANCIAL,
    DATA_DOMAIN_MACRO,
})

# ---------------------------------------------------------------
# Data classification values (V1.3)
# ---------------------------------------------------------------
DATA_CLASSIFICATION_SYNTHETIC = "synthetic_test_data"
DATA_CLASSIFICATION_MOCK = "mock_catalog_only"
DATA_CLASSIFICATION_REAL = "real_local_data"

VALID_DATA_CLASSIFICATIONS = frozenset({
    DATA_CLASSIFICATION_SYNTHETIC,
    DATA_CLASSIFICATION_MOCK,
    DATA_CLASSIFICATION_REAL,
})

# ---------------------------------------------------------------
# Valid frequencies for dataset fields (V1.3)
# ---------------------------------------------------------------
VALID_FIELD_FREQUENCIES = frozenset({
    "daily", "weekly", "monthly", "quarterly", "yearly",
})

# ---------------------------------------------------------------
# Valid dtypes for dataset fields (V1.3)
# ---------------------------------------------------------------
VALID_FIELD_DTYPES = frozenset({
    "float64", "float32", "int64", "int32", "bool", "str", "datetime64",
})
