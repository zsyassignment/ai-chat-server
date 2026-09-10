"""Stable identifiers for users, sessions, documents, and runs."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

_SAFE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def normalize_id(value: Any, default: str) -> str:
    raw = str(value or default).strip()
    if not raw:
        return default
    if len(raw) <= 96 and _SAFE.fullmatch(raw):
        return raw
    prefix = re.sub(r"[^a-zA-Z0-9_.-]", "_", raw).strip("_.-")[:24] or "id"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"[:96]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
