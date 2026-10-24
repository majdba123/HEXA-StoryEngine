"""Persistent web identities and sessions, stored beside the existing job database."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError


_EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}$")
_HASHER = PasswordHasher()
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(32))
SESSION_SECONDS = 12 * 60 * 60


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        raise ValueError("Invalid email address")
    return email


def validate_password(value: str) -> None:
    if not 12 <= len(value) <= 1024 or len(value.encode("utf-8")) > 4096:
        raise ValueError("Password must contain 12 to 1024 characters")


class Identity:
    def __init__(self, database: Path):
        self.database = database
        self._next_cleanup = 0.0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS identity_schema (version INTEGER PRIMARY KEY)")
            versions = [row[0] for row in db.execute("SELECT version FROM identity_schema")]
            if any(version > 1 or version < 1 for version in versions):
                raise RuntimeError("Unsupported identity database schema")
            db.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email_normalized TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('ADMIN','USER')), is_active INTEGER NOT NULL DEFAULT 1, deleted_at REAL, must_change_password INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL, last_login_at REAL, password_changed_at REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS identity_sessions (digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf_digest TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL)")
            db.execute("CREATE INDEX IF NOT EXISTS identity_sessions_user ON identity_sessions(user_id)")
            db.execute("CREATE TABLE IF NOT EXISTS identity_audit (id INTEGER PRIMARY KEY, actor_id TEXT, action TEXT NOT NULL, target_id TEXT, happened_at REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS login_attempts (key_digest TEXT PRIMARY KEY, failures INTEGER NOT NULL, until REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS login_attempts_until ON login_attempts(until)")
            db.execute("CREATE INDEX IF NOT EXISTS identity_sessions_expiry ON identity_sessions(expires_at)")
            db.execute("INSERT OR IGNORE INTO identity_schema(version) VALUES(1)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def audit(self, action: str, actor: str | None = None, target: str | None = None, db=None):
        if db is None:
            with self.connect() as connection:
                self.audit(action, actor, target, connection)
            return
        db.execute("INSERT INTO identity_audit(actor_id,action,target_id,happened_at) VALUES(?,?,?,?)", (actor, action, target, time.time()))

    def bootstrap(self):
        """Initialize only a clean identity database.

        The optional standard user is provisioned atomically with the first admin.
        Existing accounts are never re-seeded, reset, or elevated on restart.
        """
        admin_email = os.getenv("HEXA_ADMIN_EMAIL")
        admin_password = os.getenv("HEXA_ADMIN_BOOTSTRAP_PASSWORD")
        user_email = os.getenv("HEXA_INITIAL_USER_EMAIL")
        user_password = os.getenv("HEXA_INITIAL_USER_PASSWORD")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM users").fetchone()[0]
            if count:
                if not db.execute("SELECT 1 FROM users WHERE role='ADMIN' AND is_active=1 AND deleted_at IS NULL LIMIT 1").fetchone():
                    raise RuntimeError("No active administrator; use the documented offline restore procedure")
                return
            if not admin_email or not admin_password:
                raise RuntimeError("Initial administrator requires HEXA_ADMIN_EMAIL and HEXA_ADMIN_BOOTSTRAP_PASSWORD")
            if bool(user_email) != bool(user_password):
                raise RuntimeError("Initial user requires both HEXA_INITIAL_USER_EMAIL and HEXA_INITIAL_USER_PASSWORD")

            admin_email = normalize_email(admin_email)
            validate_password(admin_password)
            if user_email is not None:
                user_email = normalize_email(user_email)
                validate_password(user_password)
                if user_email == admin_email:
                    raise ValueError("Initial administrator and user must have different email addresses")

            now = time.time()
            admin_id = secrets.token_hex(16)
            db.execute(
                "INSERT INTO users(id,email_normalized,password_hash,role,created_at,updated_at,password_changed_at) "
                "VALUES(?,?,?,'ADMIN',?,?,?)",
                (admin_id, admin_email, _HASHER.hash(admin_password), now, now, now),
            )
            self.audit("bootstrap_admin", admin_id, admin_id, db)

            if user_email is not None:
                user_id = secrets.token_hex(16)
                db.execute(
                    "INSERT INTO users(id,email_normalized,password_hash,role,created_at,updated_at,password_changed_at,must_change_password) "
                    "VALUES(?,?,?,'USER',?,?,?,1)",
                    (user_id, user_email, _HASHER.hash(user_password), now, now, now),
                )
                self.audit("bootstrap_user", admin_id, user_id, db)

    def user(self, user_id: str):
        with self.connect() as db:
            row = db.execute("SELECT id,email_normalized,role,is_active,deleted_at,must_change_password,created_at,updated_at,last_login_at,password_changed_at FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def current(self, token: str | None):
        if not token or len(token) > 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT u.id,u.email_normalized,u.role,u.is_active,u.deleted_at,u.must_change_password,s.csrf_digest FROM identity_sessions s JOIN users u ON u.id=s.user_id WHERE s.digest=? AND s.revoked_at IS NULL AND s.expires_at>?", (digest, time.time())).fetchone()
        if row and row["is_active"] and row["deleted_at"] is None:
            return dict(row)
        return None

    def login(self, email: str, password: str, client: str):
        if len(email) > 254 or len(password) > 1024 or len(password.encode("utf-8")) > 4096:
            self.audit("login_rejected")
            return None
        try:
            email = normalize_email(email)
        except ValueError:
            email = ""
        key = hashlib.sha256(f"{client}\0{email}".encode()).hexdigest()
        client_key = hashlib.sha256(f"{client}\0*".encode()).hexdigest()
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if now >= self._next_cleanup:
                db.execute("DELETE FROM login_attempts WHERE until<?", (now - 3600,))
                db.execute("DELETE FROM identity_sessions WHERE expires_at<?", (now - 86400,))
                self._next_cleanup = now + 3600
            attempt = db.execute("SELECT failures,until FROM login_attempts WHERE key_digest=?", (key,)).fetchone()
            client_attempt = db.execute("SELECT failures,until FROM login_attempts WHERE key_digest=?", (client_key,)).fetchone()
            if ((attempt and attempt["failures"] >= 8 and attempt["until"] > now) or
                    (client_attempt and client_attempt["failures"] >= 50 and client_attempt["until"] > now)):
                self.audit("login_rejected", None, None, db)
                return None
            row = db.execute("SELECT * FROM users WHERE email_normalized=? AND deleted_at IS NULL", (email,)).fetchone()
            valid = False
            try:
                verified = _HASHER.verify(row["password_hash"] if row and row["is_active"] else _DUMMY_HASH, password)
                valid = bool(row and row["is_active"] and verified)
            except (VerifyMismatchError, VerificationError):
                pass
            if not valid:
                failures = (attempt["failures"] + 1) if attempt and attempt["until"] > now else 1
                db.execute("INSERT INTO login_attempts(key_digest,failures,until) VALUES(?,?,?) ON CONFLICT(key_digest) DO UPDATE SET failures=excluded.failures,until=excluded.until", (key, failures, now + 900))
                client_failures = (client_attempt["failures"] + 1) if client_attempt and client_attempt["until"] > now else 1
                db.execute("INSERT INTO login_attempts(key_digest,failures,until) VALUES(?,?,?) ON CONFLICT(key_digest) DO UPDATE SET failures=excluded.failures,until=excluded.until", (client_key, client_failures, now + 900))
                self.audit("login_failed", None, row["id"] if row else None, db)
                return None
            db.execute("DELETE FROM login_attempts WHERE key_digest=?", (key,))
            token = secrets.token_urlsafe(48)
            csrf = secrets.token_urlsafe(32)
            db.execute("INSERT INTO identity_sessions(digest,user_id,csrf_digest,created_at,expires_at) VALUES(?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], hashlib.sha256(csrf.encode()).hexdigest(), now, now + SESSION_SECONDS))
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
            self.audit("login_success", row["id"], row["id"], db)
            return token, csrf, self.user(row["id"])

    def revoke(self, token: str | None):
        if not token:
            return
        with self.connect() as db:
            digest = hashlib.sha256(token.encode()).hexdigest()
            row = db.execute("SELECT user_id FROM identity_sessions WHERE digest=?", (digest,)).fetchone()
            db.execute("UPDATE identity_sessions SET revoked_at=? WHERE digest=?", (time.time(), digest))
            if row:
                self.audit("logout", row["user_id"], row["user_id"], db)

    def revoke_user(self, user_id: str, db):
        db.execute("UPDATE identity_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (time.time(), user_id))

    def users(self, search: str = "", limit: int = 50, offset: int = 0):
        with self.connect() as db:
            rows = db.execute("SELECT id,email_normalized,role,is_active,deleted_at,must_change_password,created_at,updated_at,last_login_at FROM users WHERE email_normalized LIKE ? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (f"%{search}%", limit, offset)).fetchall()
            count = db.execute("SELECT count(*) FROM users WHERE email_normalized LIKE ?", (f"%{search}%",)).fetchone()[0]
        return {"items": [dict(row) for row in rows], "total": count}

    def create_user(self, actor: str, email: str, password: str, role: str = "USER"):
        email = normalize_email(email)
        validate_password(password)
        if role not in {"USER", "ADMIN"}:
            raise ValueError("Invalid role")
        user_id = secrets.token_hex(16)
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_admin_actor(actor, db)
            db.execute("INSERT INTO users(id,email_normalized,password_hash,role,created_at,updated_at,password_changed_at,must_change_password) VALUES(?,?,?,?,?,?,?,1)", (user_id, email, _HASHER.hash(password), role, now, now, now))
            self.audit("user_created", actor, user_id, db)
        return self.user(user_id)

    def change_user(self, actor: str, target: str, changes: dict):
        allowed = {"email", "role", "is_active", "delete", "password"}
        if not changes or set(changes) - allowed:
            raise ValueError("Invalid account changes")
        values = {}
        if "email" in changes:
            values["email_normalized"] = normalize_email(changes["email"])
        if "role" in changes:
            if changes["role"] not in {"USER", "ADMIN"}:
                raise ValueError("Invalid role")
            values["role"] = changes["role"]
        if "is_active" in changes:
            if type(changes["is_active"]) is not bool:
                raise ValueError("Invalid account state")
            values["is_active"] = int(changes["is_active"])
        if "password" in changes:
            validate_password(changes["password"])
            values["password_hash"] = _HASHER.hash(changes["password"])
            values["password_changed_at"] = time.time()
            values["must_change_password"] = 1
        if changes.get("delete") is True:
            values["deleted_at"] = time.time()
            values["is_active"] = 0
        if changes.get("delete") is False:
            raise ValueError("Invalid deletion request")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_admin_actor(actor, db)
            old = db.execute("SELECT role,is_active,deleted_at FROM users WHERE id=?", (target,)).fetchone()
            if not old or old["deleted_at"] is not None:
                raise LookupError("User not found")
            if actor == target and (values.get("role", old["role"]) != "ADMIN" or values.get("is_active", old["is_active"]) == 0):
                raise ValueError("Cannot disable or demote your own administrator account")
            if old["role"] == "ADMIN" and old["is_active"] and (values.get("role", old["role"]) != "ADMIN" or values.get("is_active", 1) == 0):
                active = db.execute("SELECT count(*) FROM users WHERE role='ADMIN' AND is_active=1 AND deleted_at IS NULL").fetchone()[0]
                if active <= 1:
                    raise ValueError("Cannot remove final active administrator")
            values["updated_at"] = time.time()
            fields = ", ".join(f"{column}=?" for column in values)
            db.execute(f"UPDATE users SET {fields} WHERE id=?", (*values.values(), target))
            if any(name in values for name in ("email_normalized", "password_hash", "role", "is_active", "deleted_at")):
                self.revoke_user(target, db)
            actions = []
            if "email_normalized" in values:
                actions.append("user_email_changed")
            if "role" in values and values["role"] != old["role"]:
                actions.append("user_role_changed")
            if "is_active" in values and values["is_active"] != old["is_active"]:
                actions.append("user_enabled" if values["is_active"] else "user_disabled")
            if "password_hash" in values:
                actions.append("user_password_reset")
            if "deleted_at" in values:
                actions.append("user_deleted")
            for action in actions or ["user_changed"]:
                self.audit(action, actor, target, db)
        return self.user(target)

    def change_own_password(self, user_id: str, old_password: str, new_password: str):
        validate_password(new_password)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT password_hash FROM users WHERE id=? AND is_active=1 AND deleted_at IS NULL", (user_id,)).fetchone()
            try:
                if not row or not _HASHER.verify(row["password_hash"], old_password):
                    return False
            except (VerifyMismatchError, VerificationError):
                return False
            now = time.time()
            db.execute("UPDATE users SET password_hash=?,password_changed_at=?,updated_at=?,must_change_password=0 WHERE id=?", (_HASHER.hash(new_password), now, now, user_id))
            self.revoke_user(user_id, db)
            self.audit("password_changed", user_id, user_id, db)
        return True

    @staticmethod
    def require_admin_actor(actor: str, db):
        if not db.execute("SELECT 1 FROM users WHERE id=? AND role='ADMIN' AND is_active=1 AND must_change_password=0 AND deleted_at IS NULL", (actor,)).fetchone():
            raise PermissionError("Administrator session was revoked")
