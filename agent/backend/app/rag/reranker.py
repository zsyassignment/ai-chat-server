"""Optional open-source CrossEncoder reranker with safe identity fallback."""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from app.core.config import Settings


class Reranker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._lock = threading.Lock()
        self.last_error = ""

    @property
    def enabled(self) -> bool:
        return self.settings.reranker_enabled

    def rerank(self, query: str, hits: List[Dict[str, Any]], top_n: int | None = None) -> tuple[List[Dict[str, Any]], str]:
        if not hits:
            return [], "none"
        if not self.enabled:
            return hits[: top_n or len(hits)], "disabled"
        try:
            model = self._load_model()
            pairs = [(query, hit["content"]) for hit in hits]
            scores = model.predict(pairs, show_progress_bar=False)
            ranked = [dict(hit, rerank_score=round(float(score), 6)) for hit, score in zip(hits, scores)]
            ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
            self.last_error = ""
            return ranked[: top_n or self.settings.reranker_top_n], "cross_encoder"
        except Exception as exc:
            self.last_error = str(exc)
            return hits[: top_n or len(hits)], "fallback"

    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import CrossEncoder
                except ImportError as exc:
                    raise RuntimeError(
                        "reranker enabled but sentence-transformers is not installed; "
                        "install requirements-reranker.txt"
                    ) from exc
                self._model = CrossEncoder(self.settings.reranker_model)
        return self._model
