"""Persistent learner profile, plans, and episodic memory."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.db.database import Database


class MemoryService:
    def __init__(self, database: Database):
        self.database = database

    def get_context(self, user_id: str) -> Dict[str, Any]:
        return {
            "profile": self.database.get_profile(user_id),
            "plan": self.database.get_active_plan(user_id),
            "events": self.database.list_learning_events(user_id, 8),
        }

    def infer_profile(self, text: str) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        if re.search(r"零基础|初学者|刚开始", text): updates["level"] = "beginner"
        elif re.search(r"中级|有基础|熟悉", text): updates["level"] = "intermediate"
        elif re.search(r"高级|资深|专家", text): updates["level"] = "advanced"
        minutes = re.search(r"每天.{0,8}?(\d{1,3})\s*(?:分钟|min)", text, re.I)
        hours = re.search(r"每天.{0,8}?(\d{1,2})\s*(?:小时|h)", text, re.I)
        if minutes: updates["daily_minutes"] = int(minutes.group(1))
        elif hours: updates["daily_minutes"] = int(hours.group(1)) * 60
        goal = re.search(r"(?:目标是|我想|希望)(.{3,60}?)(?:[。！!，,]|$)", text)
        if goal: updates["goal"] = goal.group(1).strip()
        if "先讲原理" in text: updates["style"] = "theory_first"
        elif "多给代码" in text: updates["style"] = "practice_first"
        elif "简洁" in text: updates["style"] = "concise"
        return updates

    def update_profile_from_text(self, user_id: str, text: str) -> Dict[str, Any]:
        current = self.database.get_profile(user_id)
        updates = self.infer_profile(text)
        if updates:
            current.update(updates)
            self.database.save_profile(user_id, current)
            self.database.add_learning_event(user_id, "profile_updated", {"updates": updates})
        return current

    def save_plan(self, user_id: str, title: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        plan = self.database.save_plan(user_id, title, items, approved=True)
        self.database.add_learning_event(user_id, "plan_created", {"plan_id": plan["id"], "title": title})
        return plan

    def update_progress(self, user_id: str, day: int, done: bool = True) -> Dict[str, Any] | None:
        plan = self.database.mark_plan_day(user_id, day, done)
        if plan:
            self.database.add_learning_event(user_id, "progress_updated", {"plan_id": plan["id"], "day": day, "done": done})
        return plan
