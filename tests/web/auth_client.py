import os

from fastapi.testclient import TestClient


class AuthenticatedTestClient(TestClient):
    """Run existing workflow regression tests under a real bootstrap administrator."""

    def __enter__(self):
        super().__enter__()
        response = self.post("/api/session", json={
            "email": os.environ["HEXA_ADMIN_EMAIL"],
            "password": os.environ["HEXA_ADMIN_BOOTSTRAP_PASSWORD"],
        })
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf"]
        return self

    def request(self, method, url, **kwargs):
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and getattr(self, "csrf", None):
            kwargs["headers"] = {**(kwargs.get("headers") or {}), "X-CSRF-Token": self.csrf}
        return super().request(method, url, **kwargs)
