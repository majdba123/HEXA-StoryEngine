from __future__ import annotations

import sqlite3

import pytest

from app.web.identity import Identity
from tools.sync_local_visual_continuity_admin import sync_local_admin


def test_local_admin_follows_env_without_resetting_jobs_or_other_users(tmp_path, monkeypatch):
    database = tmp_path / "jobs.sqlite3"
    monkeypatch.setenv("HEXA_ADMIN_EMAIL", "old@example.invalid")
    monkeypatch.setenv("HEXA_ADMIN_BOOTSTRAP_PASSWORD", "OriginalPassword123!")
    identity = Identity(database)
    identity.bootstrap()
    old_session, _, admin = identity.login("old@example.invalid", "OriginalPassword123!", "local")
    other = identity.create_user(admin["id"], "other@example.invalid", "OtherPassword123!")

    assert sync_local_admin(database, "new@example.invalid", "NewPassword123456!")
    assert not sync_local_admin(database, "new@example.invalid", "NewPassword123456!")
    assert identity.current(old_session) is None
    assert identity.login("old@example.invalid", "OriginalPassword123!", "local") is None
    assert identity.login("new@example.invalid", "NewPassword123456!", "local") is not None
    assert identity.user(other["id"])["email_normalized"] == "other@example.invalid"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM identity_audit WHERE action='local_env_admin_synced'").fetchone()[0] == 1


def test_local_admin_sync_refuses_ambiguous_or_conflicting_accounts(tmp_path, monkeypatch):
    database = tmp_path / "jobs.sqlite3"
    monkeypatch.setenv("HEXA_ADMIN_EMAIL", "admin@example.invalid")
    monkeypatch.setenv("HEXA_ADMIN_BOOTSTRAP_PASSWORD", "OriginalPassword123!")
    identity = Identity(database)
    identity.bootstrap()
    _, _, admin = identity.login("admin@example.invalid", "OriginalPassword123!", "local")
    identity.create_user(admin["id"], "other@example.invalid", "OtherPassword123!")
    with pytest.raises(ValueError, match="belongs to another"):
        sync_local_admin(database, "other@example.invalid", "NewPassword123456!")
    identity.create_user(admin["id"], "second-admin@example.invalid", "OtherPassword123!", "ADMIN")
    with pytest.raises(ValueError, match="exactly one"):
        sync_local_admin(database, "new@example.invalid", "NewPassword123456!")
    assert identity.login("admin@example.invalid", "OriginalPassword123!", "local") is not None
