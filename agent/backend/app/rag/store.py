"""Hybrid retrieval: Qdrant dense + SQLite FTS5, RRF fusion, optional reranking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from qdrant_client import QdrantClient, models

from app.core.config import Settings
from app.db.database import Database
from app.llm.client import EmbeddingClient
from app.rag.reranker import Reranker


@dataclass(frozen=True)
class RetrievalResult:
    hits: List[Dict[str, Any]]
    mode: str
    weak: bool
    reason: str = ""
    diagnostics: Dict[str, Any] | None = None


class KnowledgeStore:
    def __init__(self, settings: Settings, database: Database, embeddings: EmbeddingClient):
        self.settings = settings
        self.database = database
        self.embeddings = embeddings
        self.reranker = Reranker(settings)
        if settings.qdrant_mode == "remote":
            self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=5)
        else:
            settings.qdrant_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(settings.qdrant_path))
        self._vector_size: int | None = None

    @property
    def semantic_enabled(self) -> bool:
        return self.embeddings.enabled

    def index_document(self, user_id: str, document_id: str) -> Dict[str, Any]:
        chunks = self.database.list_chunks(user_id, document_id)
        if not chunks:
            raise ValueError("document not found")
        if not self.semantic_enabled:
            self.database.set_vector_status(user_id, document_id, "fallback", "embedding provider not configured")
            return {"vector_status": "fallback", "indexed_chunks": 0, "vector_error": "embedding provider not configured"}
        try:
            vectors = self.embeddings.embed([item["content"] for item in chunks])
            self._ensure_collection(len(vectors[0]))
            points = [
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"learningflow:{item['id']}")),
                    vector=vector,
                    payload={
                        "chunk_id": item["id"], "document_id": item["document_id"],
                        "user_id": item["user_id"], "embedding_namespace": self.settings.embedding_namespace,
                    },
                )
                for item, vector in zip(chunks, vectors)
            ]
            self.client.upsert(self.settings.qdrant_collection, points=points, wait=True)
            self.database.set_vector_status(user_id, document_id, "indexed")
            return {"vector_status": "indexed", "indexed_chunks": len(points), "vector_error": ""}
        except Exception as exc:
            self.database.set_vector_status(user_id, document_id, "failed", str(exc))
            return {"vector_status": "failed", "indexed_chunks": 0, "vector_error": str(exc)}

    def search(self, user_id: str, query: str, limit: int | None = None) -> RetrievalResult:
        final_k = limit or self.settings.max_retrieval_results
        candidate_k = max(
            self.settings.vector_recall_k,
            self.settings.keyword_recall_k,
            final_k * 4 if self.settings.max_chunks_per_document > 0 else final_k,
        )
        keyword_rows = self.database.keyword_search(user_id, query, candidate_k)
        keyword_hits = [_public_hit(item, float(item["score"]), "keyword") for item in keyword_rows]
        vector_hits: List[Dict[str, Any]] = []
        vector_error = ""
        if self.semantic_enabled:
            try:
                vector_hits = self._vector_search(user_id, query, candidate_k)
            except Exception as exc:
                vector_error = str(exc)

        fused = reciprocal_rank_fusion(
            {"vector": vector_hits, "keyword": keyword_hits},
            rrf_k=self.settings.rrf_k,
            weights={
                "vector": self.settings.rrf_vector_weight,
                "keyword": self.settings.rrf_keyword_weight,
            },
        )
        diversified = limit_chunks_per_document(
            fused, self.settings.max_chunks_per_document
        )
        if not fused:
            return RetrievalResult([], "empty", weak=True, reason=vector_error or "no retrieval hits", diagnostics={
                "vector_count": len(vector_hits), "keyword_count": len(keyword_hits), "fused_count": 0,
                "reranker": "none", "vector_error": vector_error,
                "vector_candidates": _candidate_summary(vector_hits),
                "keyword_candidates": _candidate_summary(keyword_hits),
            })

        reranked, rerank_mode = self.reranker.rerank(
            query,
            diversified,
            top_n=min(final_k, self.settings.reranker_top_n) if self.reranker.enabled else final_k,
        )
        active_paths = [name for name, hits in (("vector", vector_hits), ("keyword", keyword_hits)) if hits]
        mode = "hybrid_rrf" if len(active_paths) == 2 else (active_paths[0] if active_paths else "empty")
        if rerank_mode == "cross_encoder":
            mode += "+rerank"
        diagnostics = {
            "vector_count": len(vector_hits),
            "keyword_count": len(keyword_hits),
            "fused_count": len(fused),
            "diversified_count": len(diversified),
            "returned_count": len(reranked),
            "max_chunks_per_document": self.settings.max_chunks_per_document,
            "rrf_k": self.settings.rrf_k,
            "rrf_weights": {
                "vector": self.settings.rrf_vector_weight,
                "keyword": self.settings.rrf_keyword_weight,
            },
            "reranker": rerank_mode,
            "reranker_model": self.settings.reranker_model if self.reranker.enabled else None,
            "reranker_error": self.reranker.last_error,
            "vector_error": vector_error,
            "vector_candidates": _candidate_summary(vector_hits),
            "keyword_candidates": _candidate_summary(keyword_hits),
        }
        # Judge whether retrieval found enough evidence before presentation
        # diversity removes duplicate chunks from the same document. Otherwise
        # one strong document with multiple independently recalled chunks would
        # be misclassified as weak merely because max_chunks_per_document=1.
        weak = len(fused) < 2
        reason = vector_error or self.reranker.last_error
        return RetrievalResult(reranked, mode, weak=weak, reason=reason, diagnostics=diagnostics)

    def _vector_search(self, user_id: str, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self.settings.qdrant_mode == "remote":
            self.client.get_collections()
        vector = self.embeddings.embed([query])[0]
        self._ensure_collection(len(vector))
        response = self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=vector,
            query_filter=models.Filter(must=[
                models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                models.FieldCondition(key="embedding_namespace", match=models.MatchValue(value=self.settings.embedding_namespace)),
            ]),
            limit=top_k,
            score_threshold=self.settings.qdrant_score_threshold,
            with_payload=True,
        )
        rows = self.database.get_chunks(
            user_id,
            [point.payload.get("chunk_id") for point in response.points if point.payload],
        )
        hits = []
        for point in response.points:
            chunk_id = str((point.payload or {}).get("chunk_id", ""))
            if chunk_id in rows:
                hits.append(_public_hit(rows[chunk_id], float(point.score), "vector"))
        return hits

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def delete_document(self, user_id: str, document_id: str) -> Dict[str, Any]:
        deleted = self.database.delete_document(user_id, document_id)
        if deleted and self._collection_exists():
            self.client.delete(
                self.settings.qdrant_collection,
                points_selector=models.FilterSelector(filter=models.Filter(must=[
                    models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                    models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)),
                ])), wait=True,
            )
        return {"deleted": deleted}

    def status(self) -> Dict[str, Any]:
        return {
            "semantic_enabled": self.semantic_enabled,
            "embedding_provider": self.embeddings.provider,
            "embedding_model": self.settings.embedding_model,
            "embedding_error": self.embeddings.last_error,
            "mode": "hybrid_rrf" if self.semantic_enabled else "fts5",
            "collection": self.settings.qdrant_collection,
            "qdrant_mode": self.settings.qdrant_mode,
            "vector_recall_k": self.settings.vector_recall_k,
            "keyword_recall_k": self.settings.keyword_recall_k,
            "rrf_k": self.settings.rrf_k,
            "reranker_enabled": self.reranker.enabled,
            "reranker_model": self.settings.reranker_model if self.reranker.enabled else None,
        }

    def _collection_exists(self) -> bool:
        return self.client.collection_exists(self.settings.qdrant_collection)

    def _ensure_collection(self, vector_size: int) -> None:
        if self._collection_exists():
            info = self.client.get_collection(self.settings.qdrant_collection)
            existing = info.config.params.vectors.size
            if int(existing) != vector_size:
                raise ValueError(f"embedding dimension changed: collection={existing}, current={vector_size}; use a new collection")
        else:
            self.client.create_collection(
                self.settings.qdrant_collection,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )
        self._vector_size = vector_size


def reciprocal_rank_fusion(
    result_sets: Dict[str, List[Dict[str, Any]]],
    *,
    rrf_k: int = 60,
    weights: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    """Fuse ranked lists without comparing incomparable raw scores."""
    scores: Dict[str, float] = {}
    rows: Dict[str, Dict[str, Any]] = {}
    paths: Dict[str, List[str]] = {}
    for path, hits in result_sets.items():
        weight = float((weights or {}).get(path, 1.0))
        for rank, hit in enumerate(hits, 1):
            chunk_id = str(hit["chunk_id"])
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (rrf_k + rank)
            rows.setdefault(chunk_id, dict(hit))
            paths.setdefault(chunk_id, []).append(path)
    fused = []
    for chunk_id, score in scores.items():
        hit = rows[chunk_id]
        hit["rrf_score"] = round(score, 8)
        hit["retrieval_paths"] = sorted(set(paths[chunk_id]))
        fused.append(hit)
    fused.sort(key=lambda item: item["rrf_score"], reverse=True)
    return fused


def limit_chunks_per_document(
    hits: List[Dict[str, Any]],
    max_per_document: int,
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    """Preserve rank order while preventing one long document from crowding out others."""
    if max_per_document <= 0:
        return hits[:limit] if limit is not None else list(hits)
    counts: Dict[str, int] = {}
    selected: List[Dict[str, Any]] = []
    for hit in hits:
        document_id = str(hit.get("document_id") or hit.get("filename") or hit.get("chunk_id"))
        if counts.get(document_id, 0) >= max_per_document:
            continue
        counts[document_id] = counts.get(document_id, 0) + 1
        selected.append(hit)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def _public_hit(row: Dict[str, Any], score: float, path: str) -> Dict[str, Any]:
    return {
        "chunk_id": row["id"],
        "document_id": row["document_id"],
        "filename": row["filename"],
        "chunk_index": int(row["chunk_index"]),
        "page": row.get("page"),
        "section": row.get("section", ""),
        "content": row["content"],
        "excerpt": row["content"][:360],
        "score": round(score, 6),
        "retrieval_paths": [path],
    }


def _candidate_summary(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "chunk_id": hit["chunk_id"],
            "document_id": hit["document_id"],
            "filename": hit["filename"],
            "rank": index,
        }
        for index, hit in enumerate(hits, 1)
    ]
