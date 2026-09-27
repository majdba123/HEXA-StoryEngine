from fastapi.testclient import TestClient
# Owner-scoped Test2 coverage; historical regression content is preserved.

from app.api import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "HEXA StoryEngine"
