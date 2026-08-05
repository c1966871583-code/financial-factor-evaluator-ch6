"""
BatchRun model and store (V1.3).

A BatchRun binds a FactorBatch to one or more DatasetSnapshots
and tracks readiness per factor including field groups.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .constants import RUN_STATUS_CREATED
from .store import _get_store_dir, _now_iso

_lock = threading.Lock()


def _get_runs_file() -> Path:
    return _get_store_dir() / "batch_runs.json"


def _ensure_run_store() -> None:
    store_dir = _get_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    rfile = _get_runs_file()
    if not rfile.exists():
        tmp = rfile.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        os.replace(tmp, rfile)


def _read_runs() -> dict[str, Any]:
    _ensure_run_store()
    rfile = _get_runs_file()
    try:
        with open(rfile, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, ValueError):
        return {}


def _write_runs(data: dict[str, Any]) -> None:
    _get_store_dir().mkdir(parents=True, exist_ok=True)
    rfile = _get_runs_file()
    tmp = rfile.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, rfile)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def create_batch_run(
    batch_id: str,
    dataset_ids: list[str],
) -> dict[str, Any]:
    """Create a new BatchRun."""
    with _lock:
        store = _read_runs()
        run_id = str(uuid.uuid4())
        now = _now_iso()

        run = {
            "run_id": run_id,
            "batch_id": batch_id,
            "dataset_ids": list(dataset_ids),
            "created_at": now,
            "updated_at": now,
            "status": RUN_STATUS_CREATED,
            "dataset_validation_refs": [],
            "factor_readiness": {},
            "field_groups": [],
            "summary": {
                "total_factors": 0,
                "ready_count": 0,
                "blocked_count": 0,
                "by_blocked_reason": {},
            },
        }
        store[run_id] = run
        _write_runs(store)
        return dict(run)


def get_batch_run(run_id: str) -> dict[str, Any] | None:
    """Get a BatchRun by ID."""
    return _read_runs().get(run_id)


def list_batch_runs(
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List batch runs with pagination."""
    store = _read_runs()
    items = list(store.values())
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    total = len(items)
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


def update_batch_run(
    run_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """Update a BatchRun with readiness results."""
    with _lock:
        store = _read_runs()
        run = store.get(run_id)
        if run is None:
            return None

        for key, value in updates.items():
            run[key] = value
        run["updated_at"] = _now_iso()
        _write_runs(store)
        return dict(run)


def clear_run_store() -> None:
    """Clear all run data (for testing)."""
    with _lock:
        _write_runs({})
