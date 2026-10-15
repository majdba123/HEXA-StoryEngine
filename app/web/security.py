"""Request guards for the HEXA web UI: same-origin writes, optional access token, limits.

Local use (the default) binds 127.0.0.1 with no token. A server deployment must set
``HEXA_WEB_TOKEN``; the launcher refuses a non-loopback bind without it. Every guard
fails closed and every refusal is written to the security log.
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_PUBLIC = {"/", "/health", "/ready", "/api/session"}
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}
SESSION_COOKIE = "hexa_session"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
}


def is_loopback(host: str) -> bool:
    name = host.strip("[]").lower()
    if name in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def security_logger(storage: Path) -> logging.Logger:
    logger = logging.getLogger(f"hexa.web.security.{storage.resolve()}")
    if not logger.handlers:
        storage.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(storage / "security.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class WebGuard:
    """Same-origin writes, allowed hosts, request size and the optional access token."""

    def __init__(self, *, storage: Path, max_request_bytes: int, token: str | None = None,
                 allowed_hosts: set[str] | None = None) -> None:
        self.token = token or None
        self.max_request_bytes = max_request_bytes
        # Starlette's TestClient uses "testserver"; a public deployment lists its own name.
        self.allowed_hosts = {name.lower() for name in (allowed_hosts or set())} | _LOOPBACK_NAMES | {"testserver"}
        self.sessions: set[str] = set()
        self.log = security_logger(storage)

    @classmethod
    def from_env(cls, storage: Path, max_upload: int) -> "WebGuard":
        hosts = {row.strip() for row in os.getenv("HEXA_WEB_ALLOWED_HOSTS", "").split(",") if row.strip()}
        return cls(storage=storage, max_request_bytes=2 * max_upload + 1024 * 1024,
                   token=os.getenv("HEXA_WEB_TOKEN"), allowed_hosts=hosts)

    def login(self, supplied: str) -> str | None:
        if self.token is None or not hmac.compare_digest(supplied.encode(), self.token.encode()):
            return None
        session = secrets.token_urlsafe(32)
        self.sessions.add(session)
        return session

    def authorized(self, request: Request) -> bool:
        if self.token is None:
            return True
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), self.token.encode()):
            return True
        return request.cookies.get(SESSION_COOKIE) in self.sessions

    def refusal(self, request: Request) -> JSONResponse | None:
        host = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
        client = request.client.host if request.client else "-"
        if host.lower() not in self.allowed_hosts:
            self.log.warning("refused host=%s path=%s client=%s", host, request.url.path, client)
            return JSONResponse({"detail": "Host not allowed"}, status_code=421)
        if request.method in _UNSAFE:
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            if site == "cross-site" or (origin and (urlsplit(origin).hostname or "").lower() != host.lower()):
                self.log.warning("refused cross-origin %s %s origin=%s client=%s",
                                 request.method, request.url.path, origin, client)
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > self.max_request_bytes:
                self.log.warning("refused oversized request %s bytes client=%s", length, client)
                return JSONResponse({"detail": "Request exceeds configured size limit"}, status_code=413)
        path = request.url.path
        if path.startswith("/api/") and path not in _PUBLIC and not self.authorized(request):
            self.log.warning("refused unauthenticated %s %s client=%s", request.method, path, client)
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return None
