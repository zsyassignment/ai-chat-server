from __future__ import annotations

from pathlib import Path
import pytest

from app.core.config import Settings
from app.services.runtime import build_runtime


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "app.db",
        checkpoint_path=tmp_path / "checkpoints.db",
        skills_dir=tmp_path / "skills",
        qdrant_mode="local",
        qdrant_path=tmp_path / "qdrant",
        embedding_provider="disabled",
        embedding_namespace="test-disabled",
        require_plan_approval=True,
        max_rewrite_count=1,
    )


@pytest.fixture
def runtime(settings):
    value = build_runtime(settings)
    yield value
    value.close()
