"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_host: str = "127.0.0.1"
    app_port: int = 8010
    data_dir: Path = Path("./data")
    database_path: Path = Path("./data/learningflow.db")
    checkpoint_path: Path = Path("./data/checkpoints.db")
    skills_dir: Path = Path("./data/skills")
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1/chat/completions"
    llm_model: str = "deepseek-chat"
    llm_timeout: int = 90
    embedding_provider: str = "fastembed"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1/embeddings"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_namespace: str = "fastembed:BAAI/bge-small-zh-v1.5"
    embedding_cache_dir: Path = Path("./data/models")
    embedding_timeout: int = 30
    qdrant_mode: str = "local"
    qdrant_path: Path = Path("./data/qdrant")
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "learningflow_chunks"
    qdrant_score_threshold: float = 0.25
    chunk_size: int = 800
    chunk_overlap: int = 120
    vector_recall_k: int = 10
    keyword_recall_k: int = 10
    rrf_k: int = 60
    rrf_vector_weight: float = 0.1
    rrf_keyword_weight: float = 1.0
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_n: int = 5
    tavily_api_key: str = ""
    web_search_max_results: int = 5
    research_max_iterations: int = 6
    research_max_tool_calls: int = 10
    conversation_recent_messages: int = 10
    conversation_token_budget: int = 6000
    conversation_summary_trigger_tokens: int = 4000
    max_rewrite_count: int = 1
    max_retrieval_results: int = 5
    require_plan_approval: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", "./data"))
        chunk_size = max(200, int(os.getenv("CHUNK_SIZE", "800")))
        chunk_overlap = min(
            max(0, int(os.getenv("CHUNK_OVERLAP", "120"))), chunk_size - 1
        )
        settings = cls(
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "8010")),
            data_dir=data_dir,
            database_path=Path(os.getenv("DATABASE_PATH", str(data_dir / "learningflow.db"))),
            checkpoint_path=Path(os.getenv("CHECKPOINT_PATH", str(data_dir / "checkpoints.db"))),
            skills_dir=Path(os.getenv("SKILLS_DIR", str(data_dir / "skills"))),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1/chat/completions"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
            llm_timeout=int(os.getenv("LLM_TIMEOUT", "90")),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "fastembed").lower(),
            embedding_api_key=os.getenv("EMBEDDING_API_KEY", ""),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1/embeddings"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            embedding_namespace=os.getenv("EMBEDDING_NAMESPACE", f"{os.getenv('EMBEDDING_PROVIDER', 'fastembed').lower()}:{os.getenv('EMBEDDING_MODEL', 'BAAI/bge-small-zh-v1.5')}"),
            embedding_cache_dir=Path(os.getenv("EMBEDDING_CACHE_DIR", str(data_dir / "models"))),
            embedding_timeout=int(os.getenv("EMBEDDING_TIMEOUT", "30")),
            qdrant_mode=os.getenv("QDRANT_MODE", "local").lower(),
            qdrant_path=Path(os.getenv("QDRANT_PATH", str(data_dir / "qdrant"))),
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "learningflow_chunks"),
            qdrant_score_threshold=float(os.getenv("QDRANT_SCORE_THRESHOLD", "0.25")),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            vector_recall_k=max(1, min(int(os.getenv("VECTOR_RECALL_K", "10")), 100)),
            keyword_recall_k=max(1, min(int(os.getenv("KEYWORD_RECALL_K", "10")), 100)),
            rrf_k=max(1, int(os.getenv("RRF_K", "60"))),
            rrf_vector_weight=max(0.0, float(os.getenv("RRF_VECTOR_WEIGHT", "0.1"))),
            rrf_keyword_weight=max(0.0, float(os.getenv("RRF_KEYWORD_WEIGHT", "1.0"))),
            reranker_enabled=_bool_env("RERANKER_ENABLED", False),
            reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            reranker_top_n=max(1, min(int(os.getenv("RERANKER_TOP_N", "5")), 20)),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            web_search_max_results=max(1, min(int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5")), 10)),
            research_max_iterations=max(1, min(int(os.getenv("RESEARCH_MAX_ITERATIONS", "6")), 12)),
            research_max_tool_calls=max(1, min(int(os.getenv("RESEARCH_MAX_TOOL_CALLS", "10")), 24)),
            conversation_recent_messages=max(4, min(int(os.getenv("CONVERSATION_RECENT_MESSAGES", "10")), 30)),
            conversation_token_budget=max(1000, int(os.getenv("CONVERSATION_TOKEN_BUDGET", "6000"))),
            conversation_summary_trigger_tokens=max(500, int(os.getenv("CONVERSATION_SUMMARY_TRIGGER_TOKENS", "4000"))),
            max_rewrite_count=max(0, int(os.getenv("MAX_REWRITE_COUNT", "1"))),
            max_retrieval_results=max(1, min(int(os.getenv("MAX_RETRIEVAL_RESULTS", "5")), 20)),
            require_plan_approval=_bool_env("REQUIRE_PLAN_APPROVAL", True),
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        settings.qdrant_path.parent.mkdir(parents=True, exist_ok=True)
        settings.embedding_cache_dir.mkdir(parents=True, exist_ok=True)
        settings.skills_dir.mkdir(parents=True, exist_ok=True)
        return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
