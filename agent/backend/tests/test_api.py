from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router


def test_upload_list_and_stream(runtime):
    app = FastAPI()
    app.include_router(build_router(runtime))
    client = TestClient(app)
    response = client.post(
        "/api/documents",
        data={"user_id": "alice"},
        files={"file": ("agent.md", b"Agent Loop includes Observation.", "text/markdown")},
    )
    assert response.status_code == 200
    assert response.json()["document"]["chunk_count"] == 1
    assert client.get("/api/documents", params={"user_id": "alice"}).json()["documents"]

    with client.stream("POST", "/api/chat/stream", json={
        "message": "根据资料解释 Agent Loop", "user_id": "alice", "thread_id": "api-thread"
    }) as stream:
        body = "".join(stream.iter_text())
    assert "event: retrieval" in body
    assert "event: done" in body


def test_health_advertises_mcp_server(runtime):
    app = FastAPI()
    app.include_router(build_router(runtime))
    payload = TestClient(app).get("/api/health").json()
    mcp = payload["tools"]["mcp_server"]
    assert mcp["name"] == "learningflow-agent"
    assert mcp["http_endpoint"] == "/mcp/"
    assert "search_private_knowledge" in mcp["tools"]
    assert "create_learning_reminder" in mcp["tools"]


def test_reminder_api_create_list_fire_and_read(runtime):
    app = FastAPI()
    app.include_router(build_router(runtime))
    client = TestClient(app)
    run_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    created = client.post("/api/reminders", json={
        "user_id": "alice", "message": "复习 RAG", "run_at": run_at,
        "timezone": "Asia/Shanghai", "repeat": "once",
    })
    assert created.status_code == 200
    reminder = created.json()["reminder"]
    assert client.get("/api/reminders", params={"user_id": "alice"}).json()["reminders"]

    runtime.reminders.run_now(reminder["id"])
    notices = client.get("/api/notifications", params={"user_id": "alice", "unread_only": True}).json()["notifications"]
    assert notices[0]["message"] == "复习 RAG"
    marked = client.post(f"/api/notifications/{notices[0]['id']}/read", params={"user_id": "alice"})
    assert marked.status_code == 200
