from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest, ReminderCommand, ReminderCreateRequest, ResumeRequest, SkillToggleRequest
from app.core.ids import normalize_id
from app.rag.splitter import parse_document
from app.services.agent_service import AgentService
from app.services.runtime import ApplicationRuntime


def build_router(runtime: ApplicationRuntime) -> APIRouter:
    router = APIRouter(prefix="/api")
    agent = AgentService(runtime)

    @router.get("/health")
    def health():
        return {"status": "ok", "llm_enabled": runtime.llm.enabled, "rag": runtime.knowledge.status(), "tools": runtime.tools.status()}

    @router.post("/chat/stream")
    def chat_stream(request: ChatRequest):
        events = agent.run(user_id=request.user_id, thread_id=request.thread_id, question=request.message, history=[item.model_dump() for item in request.history])
        return StreamingResponse(_sse(events), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/runs/resume")
    def resume(request: ResumeRequest):
        return StreamingResponse(_sse(agent.resume(thread_id=request.thread_id, run_id=request.run_id, approved=request.approved)), media_type="text/event-stream")

    @router.get("/threads/{thread_id}/state")
    def thread_state(thread_id: str):
        return agent.state(thread_id)

    @router.get("/threads/{thread_id}/messages")
    def thread_messages(thread_id: str, user_id: str = "guest", limit: int = 100):
        safe_user = normalize_id(user_id, "guest")
        safe_thread = normalize_id(thread_id, "default")
        return {
            "messages": runtime.database.list_conversation_messages(safe_user, safe_thread, limit=limit),
            "summary": runtime.database.get_conversation_summary(safe_user, safe_thread),
        }

    @router.get("/runs/{run_id}")
    def get_run(run_id: str):
        run = runtime.database.get_run(run_id)
        if not run: raise HTTPException(404, "run not found")
        return run

    @router.post("/documents")
    async def upload_document(user_id: Annotated[str, Form()], file: Annotated[UploadFile, File()]):
        content = await file.read()
        if len(content) > 8 * 1024 * 1024: raise HTTPException(413, "document exceeds 8 MB")
        try:
            chunks = parse_document(
                file.filename or "document.txt",
                content,
                chunk_size=runtime.settings.chunk_size,
                overlap=runtime.settings.chunk_overlap,
            )
            document = runtime.database.add_document(normalize_id(user_id, "guest"), file.filename or "document.txt", file.content_type or "application/octet-stream", chunks)
            document.update(runtime.knowledge.index_document(normalize_id(user_id, "guest"), document["id"]))
            return {"document": document}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/documents")
    def list_documents(user_id: str = "guest"):
        return {"documents": runtime.database.list_documents(normalize_id(user_id, "guest"))}

    @router.delete("/documents/{document_id}")
    def delete_document(document_id: str, user_id: str = "guest"):
        result = runtime.knowledge.delete_document(normalize_id(user_id, "guest"), document_id)
        if not result["deleted"]: raise HTTPException(404, "document not found")
        return result

    @router.get("/learning/plan")
    def get_plan(user_id: str = "guest"):
        return {"plan": runtime.database.get_active_plan(normalize_id(user_id, "guest"))}

    @router.post("/reminders")
    def create_reminder(request: ReminderCreateRequest):
        try:
            reminder = runtime.reminders.create(
                normalize_id(request.user_id, "guest"), request.message, request.run_at,
                timezone_name=request.timezone, repeat=request.repeat, plan_day=request.plan_day,
            )
            return {"reminder": reminder}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/reminders/from-text")
    def create_reminder_from_text(request: ReminderCommand, user_id: str = "guest"):
        try:
            reminder = runtime.reminders.create_from_text(
                normalize_id(user_id, "guest"), request.message,
            )
            return {"reminder": reminder}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/reminders")
    def list_reminders(user_id: str = "guest", include_inactive: bool = False):
        return {"reminders": runtime.reminders.list(normalize_id(user_id, "guest"), include_inactive=include_inactive)}

    @router.delete("/reminders/{reminder_id}")
    def cancel_reminder(reminder_id: str, user_id: str = "guest"):
        if not runtime.reminders.cancel(normalize_id(user_id, "guest"), reminder_id):
            raise HTTPException(404, "scheduled reminder not found")
        return {"cancelled": True, "reminder_id": reminder_id}

    @router.get("/notifications")
    def list_notifications(user_id: str = "guest", unread_only: bool = False):
        return {"notifications": runtime.database.list_notifications(normalize_id(user_id, "guest"), unread_only=unread_only)}

    @router.post("/notifications/{notification_id}/read")
    def mark_notification_read(notification_id: str, user_id: str = "guest"):
        if not runtime.database.mark_notification_read(normalize_id(user_id, "guest"), notification_id):
            raise HTTPException(404, "notification not found")
        return {"read": True, "notification_id": notification_id}

    @router.post("/skills")
    async def upload_skill(user_id: Annotated[str, Form()], file: Annotated[UploadFile, File()]):
        content = await file.read()
        try:
            skill = runtime.skills.install_zip(normalize_id(user_id, "guest"), file.filename or "skill.zip", content)
            return {"skill": runtime.skills.public(skill)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/skills")
    def list_skills(user_id: str = "guest"):
        return {"skills": [runtime.skills.public(skill) for skill in runtime.skills.list(normalize_id(user_id, "guest"))]}

    @router.patch("/skills/{skill_id}")
    def toggle_skill(skill_id: str, request: SkillToggleRequest):
        skill = runtime.skills.set_enabled(normalize_id(request.user_id, "guest"), skill_id, request.enabled)
        if not skill:
            raise HTTPException(404, "skill not found")
        return {"skill": runtime.skills.public(skill)}

    @router.delete("/skills/{skill_id}")
    def delete_skill(skill_id: str, user_id: str = "guest"):
        if not runtime.skills.delete(normalize_id(user_id, "guest"), skill_id):
            raise HTTPException(404, "skill not found")
        return {"deleted": True, "skill_id": skill_id}

    return router


def _sse(events):
    for event in events:
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"
