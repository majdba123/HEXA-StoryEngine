"""Host, origin, and request-size guards for the HEXA web UI."""
from __future__ import annotations

import ipaddress
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
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
    """Same-origin writes, allowed hosts, and request size."""

    def __init__(self, *, storage: Path, max_request_bytes: int,
                 allowed_hosts: set[str] | None = None) -> None:
        self.max_request_bytes = max_request_bytes
        # Starlette's TestClient uses "testserver"; a public deployment lists its own name.
        self.allowed_hosts = {name.lower() for name in (allowed_hosts or set())} | _LOOPBACK_NAMES | {"testserver"}
        self.log = security_logger(storage)

    @classmethod
    def from_env(cls, storage: Path, max_upload: int) -> "WebGuard":
        hosts = {row.strip() for row in os.getenv("HEXA_WEB_ALLOWED_HOSTS", "").split(",") if row.strip()}
        return cls(storage=storage, max_request_bytes=2 * max_upload + 1024 * 1024,
                   allowed_hosts=hosts)

    def refusal(self, request: Request) -> JSONResponse | None:
        host = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
        client = request.client.host if request.client else "-"
        if host.lower() not in self.allowed_hosts:
            self.log.warning("refused host=%s path=%s client=%s", host, request.url.path, client)
            return JSONResponse({"detail": "Host not allowed"}, status_code=421)
        if request.method in _UNSAFE:
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            expected_authority = request.headers.get("host", "").lower()
            actual_authority = urlsplit(origin).netloc.lower() if origin else ""
            if site == "cross-site" or (origin and actual_authority != expected_authority):
                self.log.warning("refused cross-origin %s %s origin=%s client=%s",
                                 request.method, request.url.path, origin, client)
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > self.max_request_bytes:
                self.log.warning("refused oversized request %s bytes client=%s", length, client)
                return JSONResponse({"detail": "Request exceeds configured size limit"}, status_code=413)
        return None
