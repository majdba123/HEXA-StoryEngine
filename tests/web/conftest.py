import secrets

import pytest


@pytest.fixture(autouse=True)
def web_test_bootstrap(monkeypatch):
    monkeypatch.setenv("HEXA_ADMIN_EMAIL", "web-test-admin@example.invalid")
    monkeypatch.setenv("HEXA_ADMIN_BOOTSTRAP_PASSWORD", secrets.token_urlsafe(24))
