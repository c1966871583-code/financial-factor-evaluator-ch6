"""
Batch store — FactorBatch persistence (V1.3).

Stores batches in ``runtime/amr_mvp/batches.json``.
Uses the same locking/atomic-write pattern as the factor store.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import (
    BATCH_STATUS_SUBMITTED,
    BATCH_STATUS_FAILED,
    VALID_CATEGORIES,
)
from .store import _get_store_dir, _now_iso

_lock = threading.Lock()


def _get_batches_file() -> Path:
    return _get_store_dir() / "batches.json"


def _ensure_batch_store() -> None:
    store_dir = _get_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    bfile = _get_batches_file()
    if not bfile.exists():
        tmp = bfile.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        os.replace(tmp, bfile)


def _read_batches() -> dict[str, Any]:
    _ensure_batch_store()
    bfile = _get_batches_file()
    try:
        with open(bfile, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, ValueError):
        return {}


def _write_batches(data: dict[str, Any]) -> None:
    _get_store_dir().mkdir(parents=True, exist_ok=True)
    bfile = _get_batches_file()
    tmp = bfile.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, bfile)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def create_batch(batch_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new FactorBatch record."""
    with _lock:
        store = _read_batches()
        batch_id = str(uuid.uuid4())
        now = _now_iso()

        batch = {
            "batch_id": batch_id,
            "batch_name": batch_data.get("batch_name", ""),
            "description": batch_data.get("description", ""),
            "submitted_by": batch_data.get("submitted_by", ""),
            "factor_ids": [],
            "factor_count": 0,
            "created_at": now,
            "updated_at": now,
            "status": BATCH_STATUS_SUBMITTED,
            "summary": {
                "by_category": {"price_volume": 0, "financial": 0, "macro": 0},
            },
        }
        store[batch_id] = batch
        _write_batches(store)
        return dict(batch)


def get_batch(batch_id: str) -> dict[str, Any] | None:
    """Get a batch by ID."""
    return _read_batches().get(batch_id)


def list_batches(
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List batches with pagination."""
    store = _read_batches()
    items = list(store.values())
    items.sort(key=lambda b: b.get("created_at", ""), reverse=True)

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


def add_factor_to_batch(
    batch_id: str,
    factor_id: str,
    category: str,
) -> dict[str, Any] | None:
    """Add a factor to an existing batch."""
    with _lock:
        store = _read_batches()
        batch = store.get(batch_id)
        if batch is None:
            return None

        if factor_id not in batch["factor_ids"]:
            batch["factor_ids"].append(factor_id)
        batch["factor_count"] = len(batch["factor_ids"])
        batch["updated_at"] = _now_iso()

        # Update category summary
        if category in batch["summary"]["by_category"]:
            batch["summary"]["by_category"][category] = (
                batch["summary"]["by_category"].get(category, 0) + 1
            )

        _write_batches(store)
        return dict(batch)


def update_batch_status(
    batch_id: str,
    status: str,
) -> dict[str, Any] | None:
    """Update batch status."""
    with _lock:
        store = _read_batches()
        batch = store.get(batch_id)
        if batch is None:
            return None
        batch["status"] = status
        batch["updated_at"] = _now_iso()
        _write_batches(store)
        return dict(batch)


def clear_batch_store() -> None:
    """Clear all batch data (for testing)."""
    with _lock:
        _write_batches({})
