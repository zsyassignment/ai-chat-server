from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

from app.scheduling.service import ReminderService, parse_reminder_text


def future_iso(seconds: int = 60) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def test_parse_chinese_relative_and_daily_reminders():
    now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    relative = parse_reminder_text("30分钟后提醒我复习 RAG", now=now)
    assert relative["repeat"] == "once"
    assert relative["message"] == "复习 RAG"
    assert datetime.fromisoformat(relative["run_at"]).astimezone(timezone.utc) == now + timedelta(minutes=30)

    daily = parse_reminder_text("每天晚上8点提醒我检查学习目标", now=now)
    assert daily["repeat"] == "daily"
    assert daily["timezone_name"] == "Asia/Shanghai"
    assert datetime.fromisoformat(daily["run_at"]).hour == 20
def test_reminder_fires_once_and_creates_notification(runtime):
    service = runtime.reminders
    reminder = service.create("alice", "复习 Agent Loop", future_iso())
    service.run_now(reminder["id"])
    service.run_now(reminder["id"])

    stored = runtime.database.get_reminder(reminder["id"])
    notices = runtime.database.list_notifications("alice")
    assert stored["status"] == "completed"
    assert len(notices) == 1
    assert notices[0]["message"] == "复习 Agent Loop"


def test_reminder_restore_executes_overdue_job(settings):
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    from app.db.database import Database

    database = Database(settings.database_path)
    reminder = database.create_reminder(
        user_id="alice", message="恢复后执行", run_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        timezone_name="Asia/Shanghai", repeat="once",
    )
    service = ReminderService(database)
    try:
        service.start()
        assert database.get_reminder(reminder["id"])["status"] == "completed"
        assert database.list_notifications("alice")[0]["message"] == "恢复后执行"
    finally:
        service.close()


def test_apscheduler_fires_due_reminder_automatically(settings):
    from app.db.database import Database

    database = Database(settings.database_path)
    service = ReminderService(database)
    service.start()
    try:
        service.create("alice", "自动触发", future_iso(1))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not database.list_notifications("alice"):
            time.sleep(0.1)
        assert database.list_notifications("alice")[0]["message"] == "自动触发"
    finally:
        service.close()
