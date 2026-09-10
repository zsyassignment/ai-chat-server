"""APScheduler orchestration backed by SQLite reminder state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.db.database import Database


class ReminderService:
    """Schedule persistent reminders and restore unfinished jobs after restart."""

    def __init__(self, database: Database):
        self.database = database
        self.scheduler = BackgroundScheduler(timezone=timezone.utc, daemon=True)
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        self.scheduler.start(paused=True)
        self._restore_jobs()
        self.scheduler.resume()
        self.started = True

    def close(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    def create(
        self,
        user_id: str,
        message: str,
        run_at: str,
        *,
        timezone_name: str = "Asia/Shanghai",
        repeat: str = "once",
        plan_day: int | None = None,
    ) -> Dict[str, Any]:
        normalized = _normalize_schedule(run_at, timezone_name, repeat)
        target_type, target_ref = "goal", ""
        clean_message = message.strip()
        if plan_day is not None:
            plan = self.database.get_active_plan(user_id)
            item = next((entry for entry in (plan or {}).get("items", []) if int(entry["day"]) == plan_day), None)
            if not plan or not item:
                raise ValueError(f"active learning plan day {plan_day} not found")
            target_type = "plan_progress"
            target_ref = f"{plan['id']}:{plan_day}"
            clean_message = clean_message or f"检查学习计划第 {plan_day} 天：{item['topic']} - {item['task']}"
        if not clean_message:
            raise ValueError("message must not be empty")
        reminder = self.database.create_reminder(
            user_id=user_id,
            message=clean_message,
            run_at=normalized["run_at"],
            timezone_name=timezone_name,
            repeat=repeat,
            target_type=target_type,
            target_ref=target_ref,
        )
        self._schedule(reminder)
        return reminder

    def list(self, user_id: str, *, include_inactive: bool = False) -> list[Dict[str, Any]]:
        return self.database.list_reminders(user_id, include_inactive=include_inactive)

    def create_from_text(self, user_id: str, text: str) -> Dict[str, Any]:
        parsed = parse_reminder_text(text)
        return self.create(user_id, **parsed)

    def cancel(self, user_id: str, reminder_id: str) -> bool:
        cancelled = self.database.cancel_reminder(user_id, reminder_id)
        if cancelled:
            try:
                self.scheduler.remove_job(reminder_id)
            except Exception:
                pass
        return cancelled

    def run_now(self, reminder_id: str) -> None:
        reminder = self.database.get_reminder(reminder_id)
        if not reminder or reminder["status"] != "scheduled":
            return
        notification = self.database.fire_reminder(reminder_id)
        if notification:
            self.database.add_learning_event(
                reminder["user_id"],
                "reminder_fired",
                {"reminder_id": reminder_id, "message": reminder["message"]},
            )

    def _restore_jobs(self) -> None:
        for reminder in self.database.list_scheduled_reminders():
            if reminder["repeat"] == "once" and datetime.fromisoformat(reminder["run_at"]) <= datetime.now(timezone.utc):
                self.run_now(reminder["id"])
            else:
                self._schedule(reminder)

    def _schedule(self, reminder: Dict[str, Any]) -> None:
        run_at = datetime.fromisoformat(reminder["run_at"])
        repeat = reminder["repeat"]
        if repeat == "daily":
            local = run_at.astimezone(ZoneInfo(reminder["timezone"]))
            trigger = CronTrigger(hour=local.hour, minute=local.minute, timezone=reminder["timezone"])
        else:
            trigger = DateTrigger(run_date=run_at)
        self.scheduler.add_job(
            self.run_now,
            trigger=trigger,
            args=[reminder["id"]],
            id=reminder["id"],
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )


def _normalize_schedule(run_at: str, timezone_name: str, repeat: str) -> Dict[str, str]:
    if not run_at.strip():
        raise ValueError("run_at must not be empty")
    if repeat not in {"once", "daily"}:
        raise ValueError("repeat must be once or daily")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc
    try:
        value = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("run_at must be an ISO-8601 datetime") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    utc_value = value.astimezone(timezone.utc)
    if repeat == "once" and utc_value <= datetime.now(timezone.utc):
        raise ValueError("run_at must be in the future")
    return {"run_at": utc_value.isoformat(timespec="seconds")}


def parse_reminder_text(text: str, *, now: datetime | None = None) -> Dict[str, Any]:
    """Parse a deliberately small, explainable subset of Chinese reminder commands."""
    value = text.strip()
    if not value:
        raise ValueError("reminder text must not be empty")
    timezone_name = next((zone for key, zone in {
        "纽约": "America/New_York", "洛杉矶": "America/Los_Angeles", "伦敦": "Europe/London",
        "东京": "Asia/Tokyo", "首尔": "Asia/Seoul", "上海": "Asia/Shanghai", "北京": "Asia/Shanghai",
    }.items() if key in value), "Asia/Shanghai")
    zone = ZoneInfo(timezone_name)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    repeat = "daily" if re.search(r"每天|每日", value) else "once"

    relative = re.search(r"(\d{1,4})\s*(分钟|小时)后", value)
    if relative:
        amount = int(relative.group(1))
        delta = timedelta(minutes=amount) if relative.group(2) == "分钟" else timedelta(hours=amount)
        scheduled = current + delta
    else:
        clock = re.search(r"(?:(明天|后天|今天|每天|每日)\s*)?(上午|下午|晚上|中午)?\s*(\d{1,2})(?:[:：点](\d{1,2})?)?", value)
        if not clock:
            raise ValueError("无法识别提醒时间；请使用“30分钟后”或“明天20:00提醒我...”")
        marker, period, hour_raw, minute_raw = clock.groups()
        hour, minute = int(hour_raw), int(minute_raw or 0)
        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        if period == "中午" and hour < 11:
            hour += 12
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("提醒时间超出有效范围")
        day_offset = 2 if marker == "后天" else (1 if marker == "明天" else 0)
        scheduled = current.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
        if repeat == "daily" and scheduled <= current:
            scheduled += timedelta(days=1)
        if repeat == "once" and marker is None and scheduled <= current:
            scheduled += timedelta(days=1)

    plan_match = re.search(r"(?:计划)?第\s*(\d{1,3})\s*天", value)
    message = re.sub(r"^(?:请|帮我)?\s*(?:设置|创建)?\s*(?:一个)?\s*(?:学习)?提醒[:：]?\s*", "", value)
    schedule_phrase = relative.group(0) if relative else clock.group(0)
    message = message.replace(schedule_phrase, " ", 1)
    message = re.sub(r"^\s*提醒我", "", message)
    message = re.sub(r"\s+", " ", message).strip(" ，。！？,.!?") or value
    return {
        "message": message,
        "run_at": scheduled.isoformat(timespec="seconds"),
        "timezone_name": timezone_name,
        "repeat": repeat,
        "plan_day": int(plan_match.group(1)) if plan_match else None,
    }
