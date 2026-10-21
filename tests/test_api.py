from fastapi.testclient import TestClient

from app.main import app
from tests import fakes


def test_health_ui_and_ask():
    fakes.install()
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    assert "Outdoor assistant" in c.get("/").text
    r = c.post("/ask", json={"question": "Where can I run tomorrow evening near Koregaon Park?", "now": fakes.NOW.isoformat()})
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ok" and j["options"] and j["evidence"]
    assert c.post("/ask", json={"question": "hi"}).json()["status"] == "needs_clarification"
