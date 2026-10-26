"""Keep the isolated V2 test administrator in sync with the launcher's .env."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.web.identity import normalize_email, validate_password  # noqa: E402


def sync_local_admin(database: Path, email: str, password: str) -> bool:
    """Update the sole local admin, preserving jobs and all other accounts.

    This is deliberately outside Identity.bootstrap: normal web starts never reset
    existing users. The isolated V2 launcher invokes it only for its local DB.
    """
    email = normalize_email(email)
    validate_password(password)
    if not database.is_file() or database.is_symlink():
        raise ValueError("The local identity database must be a regular file")

    hasher = PasswordHasher()
    with sqlite3.connect(database, timeout=30) as db:
        db.execute("BEGIN IMMEDIATE")
        admins = db.execute(
            "SELECT id,email_normalized,password_hash FROM users "
            "WHERE role='ADMIN' AND is_active=1 AND deleted_at IS NULL"
        ).fetchall()
        if len(admins) != 1:
            raise ValueError("Expected exactly one active local administrator")
        admin_id, current_email, current_hash = admins[0]
        owner = db.execute(
            "SELECT id FROM users WHERE email_normalized=? AND deleted_at IS NULL", (email,)
        ).fetchone()
        if owner is not None and owner[0] != admin_id:
            raise ValueError("The configured email belongs to another local account")
        try:
            password_matches = hasher.verify(current_hash, password)
        except (VerifyMismatchError, VerificationError):
            password_matches = False
        if current_email == email and password_matches:
            return False

        now = time.time()
        new_hash = current_hash if password_matches else hasher.hash(password)
        db.execute(
            "UPDATE users SET email_normalized=?,password_hash=?,updated_at=?,"
            "password_changed_at=?,must_change_password=0 WHERE id=?",
            (email, new_hash, now, now, admin_id),
        )
        db.execute(
            "UPDATE identity_sessions SET revoked_at=? "
            "WHERE user_id=? AND revoked_at IS NULL", (now, admin_id)
        )
        db.execute(
            "INSERT INTO identity_audit(actor_id,action,target_id,happened_at) "
            "VALUES(?,?,?,?)", (admin_id, "local_env_admin_synced", admin_id, now)
        )
        return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Expected a local database path")
    changed = sync_local_admin(
        Path(sys.argv[1]),
        os.environ["HEXA_ADMIN_EMAIL"],
        os.environ["HEXA_ADMIN_BOOTSTRAP_PASSWORD"],
    )
    print("Local administrator credentials synchronized" if changed else "Local administrator credentials already match")
