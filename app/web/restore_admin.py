"""Explicit offline restore when the identity database has no active administrator."""
from __future__ import annotations

import argparse
import getpass
import secrets
import sqlite3
import time
from pathlib import Path

from app.web.identity import Identity, _HASHER, normalize_email, validate_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline HEXA administrator restore")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--backup-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.backup_confirmed:
        parser.error("Stop the web service and verify a database backup before using --backup-confirmed")
    if not args.db.is_file():
        parser.error("Existing SQLite database not found")
    with sqlite3.connect(args.db) as check:
        if not check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
            parser.error("This is not an existing HEXA jobs database")
    email = normalize_email(args.email)
    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords differ")
    validate_password(password)
    identity = Identity(args.db)
    now = time.time()
    user_id = secrets.token_hex(16)
    try:
        with identity.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users WHERE role='ADMIN' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone():
                parser.error("An active administrator exists; ordinary password reset is required")
            if db.execute("SELECT 1 FROM users WHERE email_normalized=?", (email,)).fetchone():
                parser.error("Email already belongs to an account; choose a distinct restore address")
            db.execute("INSERT INTO users(id,email_normalized,password_hash,role,created_at,updated_at,password_changed_at) VALUES(?,?,?,'ADMIN',?,?,?)", (user_id, email, _HASHER.hash(password), now, now, now))
            identity.audit("offline_admin_restored", None, user_id, db)
    except sqlite3.IntegrityError as exc:
        parser.error(f"Restore was refused by database constraints: {type(exc).__name__}")
    print("Restore administrator created. Restart the web service and log in.")


if __name__ == "__main__":
    main()
