"""
AMR local factor store — JSON-file-based persistence.

Stores factors in ``runtime/amr_mvp/factors.json`` relative to the repo root.
Thread-safe at a basic level (atomic write to temp file → rename).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.paths import RUNTIME_DIR

from .constants import (
    DEDUP_PHASE_PRECHECK,
    DEDUP_PHASE_VALUE_CHECK,
    REJECTION_REASON_EXACT_DUPLICATE,
    REJECTION_REASON_HIGH_SIMILARITY,
    REJECTION_REASON_UNSUPPORTED_DATA,
    STATUS_CLASSIFIED,
    STATUS_DEDUPLICATING,
    STATUS_DATA_CHECKING,
    STATUS_FAILED,
    STATUS_REJECTED,
)

# ── Path setup (mutable so tests can override) ──────────────────
_store_base_dir: Path | None = None


def _get_store_dir() -> Path:
    """Return the store directory. Tests can override via set_store_dir()."""
    if _store_base_dir is not None:
        return _store_base_dir / "amr_mvp"
    return RUNTIME_DIR / "amr_mvp"


def set_store_dir(base_dir: Path | None) -> None:
    """Atomically override the base directory used by the store.

    Test clients and long-lived application requests share this module-level
    setting.  It must therefore use the same lock as reads and writes: a
    request must not resolve one store path while a test fixture is rebinding
    the store to another path.
    """
    global _store_base_dir
    with _lock:
        _store_base_dir = base_dir


def _get_factors_file() -> Path:
    return _get_store_dir() / "factors.json"

# ── Initial review_result template ──────────────────────────────
INITIAL_REVIEW_RESULT = {
    "outcome": "pending",
    "reviewed_by": None,
    "reviewed_at": None,
    "comment": "",
}

# ── Initial precheck_result / value_check_result template ───────
INITIAL_DEDUP_RESULT_PENDING = {
    "outcome": "pending",
}

_lock = threading.RLock()


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_store() -> None:
    """Create the store directory and empty file if they don't exist."""
    store_dir = _get_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    factors_file = _get_factors_file()
    if not factors_file.exists():
        tmp = factors_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        os.replace(tmp, factors_file)


def _read_json() -> dict[str, Any]:
    """Read the full store from disk. Returns empty dict if file missing/corrupt."""
    with _lock:
        _ensure_store()
        factors_file = _get_factors_file()
        try:
            with open(factors_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("factors.json root must be a JSON object")
            return data
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"AMR 因子存储文件损坏: {factors_file}. "
                f"详情: {exc}"
            ) from exc


def _write_json(data: dict[str, Any]) -> None:
    """Atomically write JSON data: write to temp → rename."""
    with _lock:
        _get_store_dir().mkdir(parents=True, exist_ok=True)
        factors_file = _get_factors_file()
        tmp = factors_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, factors_file)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise


def create_factor(submission_data: dict[str, Any], batch_id: str | None = None) -> dict[str, Any]:
    """Create a new factor record from validated submission data.

    Parameters
    ----------
    submission_data : dict
        Validated submission payload.
    batch_id : str or None
        If part of a batch, the batch UUID (V1.3).

    Returns the full factor dict.
    """
    with _lock:
        store = _read_json()

        factor_id = str(uuid.uuid4())
        now = _now_iso()

        factor = {
            "factor_id": factor_id,
            "version": 1,
            "name": submission_data["name"],
            "category": submission_data["category"],
            "formula": submission_data["formula"],
            "description": submission_data.get("description", ""),
            "data_fields": submission_data["data_fields"],
            "code": submission_data.get("code", ""),
            "source_reference": submission_data.get("source_reference", ""),
            "submitted_by": submission_data.get("submitted_by", ""),
            "frequency": submission_data.get("frequency", "day"),
            "universe": submission_data.get("universe", ""),
            "parameters": submission_data.get("parameters", {}),
            "tags": submission_data.get("tags", []),
            # System fields
            "status": "classified",
            "failed_stage": None,
            "deduplication_phase": None,
            "rejection_reason": None,
            "processing_blocked": False,
            "blocked_stage": None,
            "blocked_reason": None,
            "batch_id": batch_id,  # V1.3
            "field_ready": False,  # V1.3
            "processing_ready": False,  # V1.3
            "catalog_supported": False,  # V1.3
            "submitted_at": now,
            "created_at": now,
            "updated_at": now,
            "error": None,
            "precheck_result": None,
            "value_check_result": None,
            "data_check_result": None,
            "validation_result": None,
            "review_result": dict(INITIAL_REVIEW_RESULT),
            "registration_result": None,
        }

        store[factor_id] = factor
        _write_json(store)
        return factor


def get_factor(factor_id: str) -> dict[str, Any] | None:
    """Get a single factor by ID."""
    with _lock:
        store = _read_json()
        return store.get(factor_id)


def list_factors(
    category: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List factors with optional filtering and pagination."""
    store = _read_json()
    items = list(store.values())

    # Filtering
    if category:
        items = [f for f in items if f.get("category") == category]
    if status:
        items = [f for f in items if f.get("status") == status]

    # Sort by created_at descending
    items.sort(key=lambda f: f.get("created_at", ""), reverse=True)

    total = len(items)

    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0

    return {
        "items": page_items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


def get_summary() -> dict[str, Any]:
    """Return dashboard summary statistics (V1.3).

    Includes blocked_count, by_blocked_reason, field_ready_count,
    processing_ready_count, batch_count, batch_run_count.
    """
    store = _read_json()
    items = list(store.values())

    total = len(items)

    by_category: dict[str, int] = {"price_volume": 0, "financial": 0, "macro": 0}
    by_status: dict[str, int] = {}
    registered_count = 0
    rejected_count = 0
    duplicate_count = 0
    validation_failed_count = 0
    blocked_count = 0
    field_ready_count = 0
    processing_ready_count = 0
    by_blocked_reason: dict[str, int] = {}

    for f in items:
        cat = f.get("category", "")
        if cat in by_category:
            by_category[cat] += 1

        st = f.get("status", "")
        by_status[st] = by_status.get(st, 0) + 1

        if st == "registered":
            registered_count += 1
        if st == "rejected":
            rejected_count += 1

        # V1.3: field_ready and processing_ready
        if f.get("field_ready") is True:
            field_ready_count += 1
        if f.get("processing_ready") is True:
            processing_ready_count += 1

        # Count processing_blocked (V1.2+)
        if f.get("processing_blocked") is True:
            blocked_count += 1
            reason = f.get("blocked_reason", "unknown")
            by_blocked_reason[reason] = by_blocked_reason.get(reason, 0) + 1

        # Count duplicates
        precheck = f.get("precheck_result")
        if precheck and precheck.get("outcome") == "exact_duplicate":
            duplicate_count += 1
        value_check = f.get("value_check_result")
        if value_check and value_check.get("outcome") == "high_similarity":
            duplicate_count += 1

        # Validation failed
        vr = f.get("validation_result")
        if vr and vr.get("outcome") == "failed":
            validation_failed_count += 1

    # ── Batch stats (V1.3) ──────────────────────────────────
    batch_count = 0
    batch_run_count = 0
    try:
        from .batch_store import _read_batches
        batches = _read_batches()
        batch_count = len(batches)
    except Exception:
        pass

    try:
        from .batch_run import _read_runs
        runs = _read_runs()
        batch_run_count = len(runs)
    except Exception:
        pass

    return {
        "total_factors": total,
        "by_category": by_category,
        "by_status": by_status,
        "registered_count": registered_count,
        "rejected_count": rejected_count,
        "duplicate_count": duplicate_count,
        "validation_failed_count": validation_failed_count,
        "blocked_count": blocked_count,
        "by_blocked_reason": by_blocked_reason,
        "field_ready_count": field_ready_count,
        "processing_ready_count": processing_ready_count,
        "batch_count": batch_count,
        "batch_run_count": batch_run_count,
        "generated_at": _now_iso(),
    }


def read_raw_store() -> dict[str, Any]:
    """Read the entire raw store dictionary (thread-safe).

    Returns factor_id → record mapping.
    """
    with _lock:
        return _read_json()


def apply_precheck_result(
    factor_id: str,
    dedup_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a precheck deduplication result to a factor record.

    Updates the factor's precheck_result, value_check_result, and status
    based on the dedup outcome.  Returns the updated factor record, or
    None if the factor was not found.

    Status transitions
    ------------------
    - ``deduplicating`` / ``precheck`` → set at start of precheck
      (caller must set this BEFORE running the check, then call this
      function to finalize).
    - outcome ``not_duplicate`` → status=classified, dedup_phase=null
    - outcome ``exact_duplicate`` → status=rejected,
      rejection_reason=exact_duplicate, dedup_phase=null
    - outcome ``failed`` → status=failed, failed_stage=pre_deduplication,
      dedup_phase=null

    Thread-safe.
    """
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        now = _now_iso()
        precheck_outcome = dedup_result["precheck"]["outcome"]
        value_check = dedup_result.get("value_check", {"outcome": "not_run"})

        factor["precheck_result"] = dedup_result["precheck"]
        existing_value_check = factor.get("value_check_result")
        final_value_check = _is_final_value_check(existing_value_check)
        if not final_value_check:
            factor["value_check_result"] = value_check
        factor["updated_at"] = now
        factor["deduplication_phase"] = None

        if final_value_check:
            if existing_value_check.get("outcome") == "high_similarity":
                factor["status"] = STATUS_REJECTED
                factor["rejection_reason"] = REJECTION_REASON_HIGH_SIMILARITY
            else:
                factor["status"] = STATUS_CLASSIFIED
                factor["rejection_reason"] = None
        elif precheck_outcome == "exact_duplicate":
            factor["status"] = STATUS_REJECTED
            factor["rejection_reason"] = REJECTION_REASON_EXACT_DUPLICATE
        elif precheck_outcome == "failed":
            factor["status"] = STATUS_FAILED
            factor["failed_stage"] = "pre_deduplication"
        else:
            # not_duplicate: restore to classified
            factor["status"] = STATUS_CLASSIFIED

        _write_json(store)
        return factor


def set_value_checking_status(factor_id: str) -> dict[str, Any] | None:
    """Set a factor's status to deduplicating / value_check phase."""
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        factor["status"] = STATUS_DEDUPLICATING
        factor["deduplication_phase"] = DEDUP_PHASE_VALUE_CHECK
        factor["failed_stage"] = None
        factor["error"] = None
        factor["updated_at"] = _now_iso()
        _write_json(store)
        return factor


def apply_value_check_result(
    factor_id: str,
    value_check_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Persist a numeric-dedup result and finalize its status transition."""
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        outcome = value_check_result.get("outcome")
        factor["value_check_result"] = value_check_result
        factor["deduplication_phase"] = None
        factor["failed_stage"] = None
        factor["error"] = None
        factor["updated_at"] = _now_iso()

        if outcome == "high_similarity":
            factor["status"] = STATUS_REJECTED
            factor["rejection_reason"] = REJECTION_REASON_HIGH_SIMILARITY
        else:
            factor["status"] = STATUS_CLASSIFIED
            factor["rejection_reason"] = None

        _write_json(store)
        return factor


def apply_value_check_failure(
    factor_id: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any] | None:
    """Record an unexpected numeric-dedup failure without leaving a stale phase."""
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        now = _now_iso()
        factor["value_check_result"] = {
            "status": "not_run",
            "outcome": "not_run",
            "method_version": "value_check_v1",
            "issue_codes": [error_code],
            "error": {
                "code": error_code,
                "message": error_message,
            },
            "completed_at": now,
        }
        factor["status"] = STATUS_FAILED
        factor["failed_stage"] = "value_deduplication"
        factor["deduplication_phase"] = None
        factor["error"] = {
            "code": error_code,
            "message": error_message,
        }
        factor["updated_at"] = now
        _write_json(store)
        return factor


def _is_final_value_check(value_check_result: Any) -> bool:
    if not isinstance(value_check_result, dict):
        return False
    return (
        value_check_result.get("status") == "completed"
        or value_check_result.get("outcome") == "high_similarity"
    )


def set_deduplicating_status(factor_id: str) -> dict[str, Any] | None:
    """Set a factor's status to deduplicating / precheck phase.

    Returns updated factor or None if not found.
    Thread-safe.
    """
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        factor["status"] = STATUS_DEDUPLICATING
        factor["deduplication_phase"] = DEDUP_PHASE_PRECHECK
        factor["updated_at"] = _now_iso()
        _write_json(store)
        return factor


def set_data_checking_status(factor_id: str) -> dict[str, Any] | None:
    """Set a factor's status to data_checking.

    Returns updated factor or None if not found.
    Thread-safe.
    """
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        factor["status"] = STATUS_DATA_CHECKING
        factor["deduplication_phase"] = None
        factor["updated_at"] = _now_iso()
        _write_json(store)
        return factor


def apply_data_check_result(
    factor_id: str,
    check_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a data check result to a factor record (V1.2).

    Uses the status_transition embedded in the check_result to update
    the factor's status, data_check_result, processing_blocked,
    blocked_stage, blocked_reason, etc.

    V1.2: When fields are unavailable, the factor is **blocked** (not rejected).
    status remains ``classified``, ``processing_blocked=True``,
    ``blocked_stage=data_check``, ``blocked_reason=data_unavailable``.

    Returns the updated factor record, or None if not found.
    Thread-safe.
    """
    with _lock:
        store = _read_json()
        factor = store.get(factor_id)
        if factor is None:
            return None

        now = _now_iso()
        transition = check_result.get("status_transition", {})

        factor["data_check_result"] = check_result["data_check_result"]
        factor["status"] = transition.get("status", factor["status"])
        factor["failed_stage"] = transition.get("failed_stage")
        factor["rejection_reason"] = transition.get("rejection_reason")
        factor["error"] = transition.get("error")
        # V1.2: blocked fields
        factor["processing_blocked"] = transition.get("processing_blocked", False)
        factor["blocked_stage"] = transition.get("blocked_stage")
        factor["blocked_reason"] = transition.get("blocked_reason")
        factor["updated_at"] = now

        _write_json(store)
        return factor


def clear_store() -> None:
    """Clear all data (for testing only)."""
    with _lock:
        _write_json({})
