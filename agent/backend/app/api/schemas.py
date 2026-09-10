from __future__ import annotations

from typing import Dict, List, Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    user_id: str = "guest"
    thread_id: str = "default"
    history: List[ChatMessage] = []


class ResumeRequest(BaseModel):
    run_id: str
    thread_id: str
    approved: bool


class ProgressRequest(BaseModel):
    user_id: str
    day: int = Field(ge=1, le=365)
    done: bool = True


class ReminderCreateRequest(BaseModel):
    user_id: str = "guest"
    message: str = Field(default="", max_length=1000)
    run_at: str = Field(description="ISO-8601 datetime, for example 2026-09-03T20:00:00+08:00")
    timezone: str = "Asia/Shanghai"
    repeat: Literal["once", "daily"] = "once"
    plan_day: int | None = Field(default=None, ge=1, le=365)


class ReminderCommand(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class SkillToggleRequest(BaseModel):
    user_id: str = "guest"
    enabled: bool
