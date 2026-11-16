"""Shared test fixtures: redirect both data files to tmp_path for every test,
so no test ever reads or writes the real data/approvals.json or data/budget.json.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import approvals as approvals_mod  # noqa: E402
from tools import finance_tools  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_data_files(tmp_path, monkeypatch):
    """Point BUDGET_FILE and APPROVALS_FILE at fresh tmp_path copies for every test.

    Also sets up the named budget_file / approvals_file attributes on the fixture
    so tests that need to inspect the files can request those fixtures directly.
    """
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(json.dumps({"total_cap": 500000, "current_spend": 420000}))
    monkeypatch.setattr(finance_tools, "BUDGET_FILE", budget_path)

    approvals_path = tmp_path / "approvals.json"
    approvals_path.write_text("[]\n")
    monkeypatch.setattr(approvals_mod, "APPROVALS_FILE", approvals_path)


@pytest.fixture()
def budget_file(tmp_path):
    """Return the tmp_path budget file created by isolate_data_files (already monkeypatched)."""
    return tmp_path / "budget.json"


@pytest.fixture()
def approvals_file(tmp_path):
    """Return the tmp_path approvals file created by isolate_data_files (already monkeypatched)."""
    return tmp_path / "approvals.json"
