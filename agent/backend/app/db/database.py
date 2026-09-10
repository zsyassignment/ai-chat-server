"""SQLite source of truth for documents, learner memory, plans, and run traces."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from app.core.ids import new_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._schema_lock, self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    vector_status TEXT NOT NULL DEFAULT 'pending',
                    vector_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id, created_at);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    page INTEGER,
                    section TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, chunk_index);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    chunk_id UNINDEXED,
                    user_id UNINDEXED,
                    filename,
                    section,
                    content,
                    search_tokens,
                    tokenize='unicode61'
                );
                CREATE TABLE IF NOT EXISTS learner_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_plans (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    approved INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_user ON learning_plans(user_id, active);
                CREATE TABLE IF NOT EXISTS learning_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_user ON learning_events(user_id, created_at);
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    intent TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    question TEXT NOT NULL,
                    final_answer TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_runs_user ON agent_runs(user_id, started_at);
                CREATE TABLE IF NOT EXISTS agent_steps (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    step_index INTEGER NOT NULL,
                    node TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_steps_run ON agent_steps(run_id, step_index);
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    repeat TEXT NOT NULL DEFAULT 'once',
                    target_type TEXT NOT NULL DEFAULT 'goal',
                    target_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    last_fired_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, status, run_at);
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    reminder_id TEXT REFERENCES reminders(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read, created_at);
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    run_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, thread_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_thread ON conversation_messages(user_id, thread_id, sequence);
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    through_sequence INTEGER NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, thread_id)
                );
                """
            )
            fts_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(chunk_fts)").fetchall()
            }
            if "search_tokens" not in fts_columns:
                conn.execute("DROP TABLE chunk_fts")
                conn.execute(
                    """CREATE VIRTUAL TABLE chunk_fts USING fts5(
                        chunk_id UNINDEXED, user_id UNINDEXED, filename, section,
                        content, search_tokens, tokenize='unicode61'
                    )"""
                )
                existing = conn.execute(
                    """SELECT c.id,c.user_id,d.filename,c.section,c.content
                       FROM chunks c JOIN documents d ON d.id=c.document_id"""
                ).fetchall()
                for row in existing:
                    conn.execute(
                        """INSERT INTO chunk_fts(
                            chunk_id,user_id,filename,section,content,search_tokens
                        ) VALUES(?,?,?,?,?,?)""",
                        (
                            row["id"], row["user_id"], row["filename"], row["section"],
                            row["content"], _fts_token_text(
                                f"{row['filename']} {row['section']} {row['content']}"
                            ),
                        ),
                    )
            reminder_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()
            }
            if "target_type" not in reminder_columns:
                conn.execute("ALTER TABLE reminders ADD COLUMN target_type TEXT NOT NULL DEFAULT 'goal'")
            if "target_ref" not in reminder_columns:
                conn.execute("ALTER TABLE reminders ADD COLUMN target_ref TEXT NOT NULL DEFAULT ''")

    def add_document(self, user_id: str, filename: str, content_type: str, chunks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        document_id = new_id("doc")
        rows = list(chunks)
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO documents(id,user_id,filename,content_type,created_at) VALUES(?,?,?,?,?)",
                (document_id, user_id, filename, content_type, now),
            )
            for index, item in enumerate(rows):
                chunk_id = new_id("chunk")
                content = str(item["content"])
                page = item.get("page")
                section = str(item.get("section") or "")
                conn.execute(
                    "INSERT INTO chunks(id,document_id,user_id,chunk_index,page,section,content) VALUES(?,?,?,?,?,?,?)",
                    (chunk_id, document_id, user_id, index, page, section, content),
                )
                conn.execute(
                    """INSERT INTO chunk_fts(
                        chunk_id,user_id,filename,section,content,search_tokens
                    ) VALUES(?,?,?,?,?,?)""",
                    (
                        chunk_id, user_id, filename, section, content,
                        _fts_token_text(f"{filename} {section} {content}"),
                    ),
                )
        return {"id": document_id, "filename": filename, "content_type": content_type, "chunk_count": len(rows), "vector_status": "pending", "created_at": now}

    def list_documents(self, user_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id,d.filename,d.content_type,d.vector_status,d.vector_error,d.created_at,
                       COUNT(c.id) AS chunk_count
                FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
                WHERE d.user_id=? GROUP BY d.id ORDER BY d.created_at DESC
                """, (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_chunks(self, user_id: str, document_id: str | None = None) -> List[Dict[str, Any]]:
        sql = """
            SELECT c.id,c.document_id,c.user_id,c.chunk_index,c.page,c.section,c.content,
                   d.filename,d.content_type
            FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE c.user_id=?
        """
        params: list[Any] = [user_id]
        if document_id:
            sql += " AND c.document_id=?"
            params.append(document_id)
        sql += " ORDER BY d.created_at DESC,c.chunk_index ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_chunks(self, user_id: str, chunk_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        ids = list(dict.fromkeys(str(item) for item in chunk_ids))[:100]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.id,c.document_id,c.user_id,c.chunk_index,c.page,c.section,c.content,
                       d.filename,d.content_type
                FROM chunks c JOIN documents d ON d.id=c.document_id
                WHERE c.user_id=? AND c.id IN ({marks})
                """, (user_id, *ids),
            ).fetchall()
        return {str(row["id"]): dict(row) for row in rows}

    def keyword_search(self, user_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
        terms = [token for token in _search_terms(query) if token]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:24])
        with self.connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT f.chunk_id, bm25(chunk_fts) AS rank
                    FROM chunk_fts f WHERE f.user_id=? AND chunk_fts MATCH ?
                    ORDER BY rank LIMIT ?
                    """, (user_id, fts_query, max(1, min(limit, 20))),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        chunks = self.get_chunks(user_id, [row["chunk_id"] for row in rows])
        return [chunks[row["chunk_id"]] | {"score": 1.0 / (1.0 + abs(float(row["rank"])))} for row in rows if row["chunk_id"] in chunks]

    def set_vector_status(self, user_id: str, document_id: str, status: str, error: str = "") -> None:
        with self.connect() as conn:
            conn.execute("UPDATE documents SET vector_status=?,vector_error=? WHERE id=? AND user_id=?", (status[:32], error[:1000], document_id, user_id))

    def delete_document(self, user_id: str, document_id: str) -> bool:
        with self.connect() as conn:
            ids = [row["id"] for row in conn.execute("SELECT id FROM chunks WHERE user_id=? AND document_id=?", (user_id, document_id)).fetchall()]
            for chunk_id in ids:
                conn.execute("DELETE FROM chunk_fts WHERE chunk_id=?", (chunk_id,))
            cursor = conn.execute("DELETE FROM documents WHERE id=? AND user_id=?", (document_id, user_id))
        return cursor.rowcount > 0

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT profile_json FROM learner_profiles WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(row["profile_json"]) if row else {}

    def save_profile(self, user_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        clean = {str(key): value for key, value in profile.items() if value not in (None, "")}
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO learner_profiles(user_id,profile_json,updated_at) VALUES(?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json,updated_at=excluded.updated_at""",
                (user_id, json.dumps(clean, ensure_ascii=False), utc_now()),
            )
        return clean

    def save_plan(self, user_id: str, title: str, items: List[Dict[str, Any]], approved: bool = True) -> Dict[str, Any]:
        plan_id, now = new_id("plan"), utc_now()
        normalized = [{"day": int(item.get("day", i)), "topic": str(item.get("topic", "")), "task": str(item.get("task", "")), "done": bool(item.get("done", False))} for i, item in enumerate(items, 1)]
        with self.connect() as conn:
            conn.execute("UPDATE learning_plans SET active=0 WHERE user_id=?", (user_id,))
            conn.execute(
                "INSERT INTO learning_plans(id,user_id,title,items_json,active,approved,created_at,updated_at) VALUES(?,?,?,?,1,?,?,?)",
                (plan_id, user_id, title, json.dumps(normalized, ensure_ascii=False), int(approved), now, now),
            )
        return {"id": plan_id, "title": title, "items": normalized, "approved": approved, "updated_at": now}

    def get_active_plan(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT id,title,items_json,approved,updated_at FROM learning_plans WHERE user_id=? AND active=1 ORDER BY updated_at DESC LIMIT 1", (user_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "title": row["title"], "items": json.loads(row["items_json"]), "approved": bool(row["approved"]), "updated_at": row["updated_at"]}

    def mark_plan_day(self, user_id: str, day: int, done: bool) -> Optional[Dict[str, Any]]:
        plan = self.get_active_plan(user_id)
        if not plan:
            return None
        changed = False
        for item in plan["items"]:
            if int(item["day"]) == day:
                item["done"], changed = done, True
        if not changed:
            return None
        now = utc_now()
        with self.connect() as conn:
            conn.execute("UPDATE learning_plans SET items_json=?,updated_at=? WHERE id=?", (json.dumps(plan["items"], ensure_ascii=False), now, plan["id"]))
        plan["updated_at"] = now
        return plan

    def add_learning_event(self, user_id: str, event_type: str, content: Dict[str, Any]) -> str:
        event_id = new_id("event")
        with self.connect() as conn:
            conn.execute("INSERT INTO learning_events(id,user_id,event_type,content_json,created_at) VALUES(?,?,?,?,?)", (event_id, user_id, event_type, json.dumps(content, ensure_ascii=False), utc_now()))
        return event_id

    def list_learning_events(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id,event_type,content_json,created_at FROM learning_events WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 50)))).fetchall()
        return [{"id": row["id"], "event_type": row["event_type"], "content": json.loads(row["content_json"]), "created_at": row["created_at"]} for row in rows]

    def create_run(self, user_id: str, thread_id: str, question: str) -> str:
        run_id = new_id("run")
        with self.connect() as conn:
            conn.execute("INSERT INTO agent_runs(id,user_id,thread_id,status,question,started_at) VALUES(?,?,?,?,?,?)", (run_id, user_id, thread_id, "running", question, utc_now()))
        return run_id

    def update_run(self, run_id: str, *, status: str, intent: str = "", answer: str = "", error: str = "") -> None:
        finished = utc_now() if status in {"completed", "failed", "interrupted"} else None
        with self.connect() as conn:
            conn.execute("UPDATE agent_runs SET status=?,intent=COALESCE(NULLIF(?,''),intent),final_answer=?,error=?,finished_at=? WHERE id=?", (status, intent, answer, error, finished, run_id))

    def add_step(self, run_id: str, step_index: int, node: str, event_type: str, payload: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO agent_steps(id,run_id,step_index,node,event_type,payload_json,created_at) VALUES(?,?,?,?,?,?,?)", (new_id("step"), run_id, step_index, node, event_type, json.dumps(payload, ensure_ascii=False, default=str), utc_now()))

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            run = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return None
            steps = conn.execute("SELECT step_index,node,event_type,payload_json,created_at FROM agent_steps WHERE run_id=? ORDER BY step_index", (run_id,)).fetchall()
        result = dict(run)
        result["steps"] = [dict(row) | {"payload": json.loads(row["payload_json"])} for row in steps]
        for item in result["steps"]:
            item.pop("payload_json", None)
        return result

    def create_reminder(
        self, *, user_id: str, message: str, run_at: str, timezone_name: str,
        repeat: str, target_type: str = "goal", target_ref: str = "",
    ) -> Dict[str, Any]:
        if not message:
            raise ValueError("message must not be empty")
        reminder_id, now = new_id("reminder"), utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO reminders(
                       id,user_id,message,run_at,timezone,repeat,target_type,target_ref,status,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?, 'scheduled',?,?)""",
                (reminder_id, user_id, message[:1000], run_at, timezone_name, repeat, target_type, target_ref, now, now),
            )
        return self.get_reminder(reminder_id) or {}

    def get_reminder(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        return dict(row) if row else None

    def list_reminders(self, user_id: str, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM reminders WHERE user_id=?"
        if not include_inactive:
            sql += " AND status='scheduled'"
        sql += " ORDER BY run_at ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_scheduled_reminders(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM reminders WHERE status='scheduled' ORDER BY run_at").fetchall()
        return [dict(row) for row in rows]

    def cancel_reminder(self, user_id: str, reminder_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE reminders SET status='cancelled',updated_at=? WHERE id=? AND user_id=? AND status='scheduled'",
                (utc_now(), reminder_id, user_id),
            )
        return cursor.rowcount > 0

    def fire_reminder(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        now = utc_now()
        with self.connect() as conn:
            reminder = conn.execute("SELECT * FROM reminders WHERE id=? AND status='scheduled'", (reminder_id,)).fetchone()
            if not reminder:
                return None
            if reminder["repeat"] == "once":
                claimed = conn.execute(
                    "UPDATE reminders SET status='completed',last_fired_at=?,updated_at=? WHERE id=? AND status='scheduled'",
                    (now, now, reminder_id),
                )
                if claimed.rowcount == 0:
                    return None
            notification_id = new_id("notification")
            conn.execute(
                "INSERT INTO notifications(id,user_id,reminder_id,title,message,created_at) VALUES(?,?,?,?,?,?)",
                (notification_id, reminder["user_id"], reminder_id, "学习提醒", reminder["message"], now),
            )
            if reminder["repeat"] == "daily":
                conn.execute(
                    "UPDATE reminders SET last_fired_at=?,updated_at=? WHERE id=? AND status='scheduled'",
                    (now, now, reminder_id),
                )
        return {"id": notification_id, "user_id": reminder["user_id"], "reminder_id": reminder_id, "title": "学习提醒", "message": reminder["message"], "read": False, "created_at": now}

    def list_notifications(self, user_id: str, *, unread_only: bool = False, limit: int = 20) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM notifications WHERE user_id=?"
        if unread_only:
            sql += " AND read=0"
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(sql, (user_id, max(1, min(limit, 100)))).fetchall()
        return [dict(row) | {"read": bool(row["read"])} for row in rows]

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (notification_id, user_id))
        return cursor.rowcount > 0

    def add_conversation_message(self, user_id: str, thread_id: str, role: str, content: str, *, run_id: str = "") -> Dict[str, Any]:
        from app.conversation.service import estimate_tokens

        message_id, now = new_id("message"), utc_now()
        with self.connect() as conn:
            sequence = int(conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 AS next FROM conversation_messages WHERE user_id=? AND thread_id=?",
                (user_id, thread_id),
            ).fetchone()["next"])
            conn.execute(
                """INSERT INTO conversation_messages(
                       id,user_id,thread_id,sequence,role,content,token_estimate,run_id,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (message_id, user_id, thread_id, sequence, role, content, estimate_tokens(content), run_id, now),
            )
        return {"id": message_id, "sequence": sequence, "role": role, "content": content, "created_at": now}

    def list_conversation_messages(self, user_id: str, thread_id: str, *, limit: int = 100, after_sequence: int = 0) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,sequence,role,content,token_estimate,run_id,created_at
                   FROM conversation_messages WHERE user_id=? AND thread_id=? AND sequence>?
                   ORDER BY sequence DESC LIMIT ?""",
                (user_id, thread_id, after_sequence, max(1, min(limit, 1000))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def list_conversation_messages_after(self, user_id: str, thread_id: str, sequence: int, *, limit: int = 1000) -> List[Dict[str, Any]]:
        """Read oldest unsummarized messages first so summary coverage cannot skip gaps."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,sequence,role,content,token_estimate,run_id,created_at
                   FROM conversation_messages WHERE user_id=? AND thread_id=? AND sequence>?
                   ORDER BY sequence ASC LIMIT ?""",
                (user_id, thread_id, sequence, max(1, min(limit, 5000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation_summary(self, user_id: str, thread_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT version,through_sequence,summary_json,created_at,updated_at FROM conversation_summaries WHERE user_id=? AND thread_id=?",
                (user_id, thread_id),
            ).fetchone()
        if not row:
            return None
        return dict(row) | {"summary": json.loads(row["summary_json"])}

    def save_conversation_summary(self, user_id: str, thread_id: str, summary: Dict[str, Any], *, through_sequence: int) -> Dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT version,created_at FROM conversation_summaries WHERE user_id=? AND thread_id=?",
                (user_id, thread_id),
            ).fetchone()
            version = int(existing["version"]) + 1 if existing else 1
            created = existing["created_at"] if existing else now
            conn.execute(
                """INSERT INTO conversation_summaries(user_id,thread_id,version,through_sequence,summary_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,thread_id) DO UPDATE SET
                   version=excluded.version,through_sequence=excluded.through_sequence,
                   summary_json=excluded.summary_json,updated_at=excluded.updated_at""",
                (user_id, thread_id, version, through_sequence, json.dumps(summary, ensure_ascii=False), created, now),
            )
        return {"version": version, "through_sequence": through_sequence, "summary": summary, "created_at": created, "updated_at": now}


def _search_terms(query: str) -> List[str]:
    import re
    english = re.findall(r"[a-zA-Z0-9_+#.-]{2,}", query.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    terms = english + chinese
    for run in chinese:
        terms.extend(run[index:index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(terms))


def _fts_token_text(text: str) -> str:
    return " ".join(_search_terms(text))
