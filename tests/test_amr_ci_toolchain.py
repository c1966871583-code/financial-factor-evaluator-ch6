"""Regression contract for the GitHub Actions Python toolchain."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pydantic
import pytest
from pydantic import BaseModel, ConfigDict, model_validator

PROJECT = Path(__file__).resolve().parents[1]


class WorkflowToolchainContract(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    path: Path
    required_fragments: tuple[str, ...] = (
        "astral-sh/setup-uv@",
        "cache-dependency-glob: uv.lock",
        "uv sync --frozen",
        "uv run --frozen ruff check",
        "uv run --frozen python -m pytest",
        "tests/test_amr_ci_toolchain.py",
    )

    @model_validator(mode="after")
    def validate_workflow(self) -> WorkflowToolchainContract:
        if not self.path.is_file():
            raise ValueError(f"workflow does not exist: {self.path}")
        content = self.path.read_text(encoding="utf-8")
        missing = [item for item in self.required_fragments if item not in content]
        if missing:
            raise ValueError(
                f"{self.path.name} misses locked CI fragments: {missing}"
            )
        return self


@pytest.mark.parametrize(
    "workflow",
    ("ci.yml", "amr-check.yml"),
)
def test_workflow_uses_locked_uv_ruff_pytest_contract(workflow):
    contract = WorkflowToolchainContract(
        path=PROJECT / ".github" / "workflows" / workflow
    )
    assert contract.path.name == workflow


def test_pydantic_v2_is_locked_in_dev_dependencies():
    configuration = tomllib.loads(
        (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    )
    dev_dependencies = configuration["dependency-groups"]["dev"]
    assert any(item.startswith("pydantic>=2.10") for item in dev_dependencies)
    assert pydantic.VERSION.startswith("2.")
