"""This suite certifies the strict carrier contract: every defect stops with its typed code.

Production repairs instead of stopping (app/story/carrier_repair.py, 2026-10-21); the same
defect families are certified in repair mode by tests/test3/test_carrier_repair_matrix.py.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _strict_story_contract(monkeypatch):
    monkeypatch.setattr("app.story.carrier_repair.STORY_CARRIER_REPAIR", False)
