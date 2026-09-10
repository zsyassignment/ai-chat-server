"""Deterministic information-retrieval metrics with explicit binary relevance."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List


def retrieval_metrics(hits: List[Dict[str, Any]], relevant_documents: Iterable[str], k: int = 5) -> Dict[str, float | None]:
    relevant = set(relevant_documents)
    ranked = [str(hit.get("filename", "")) for hit in hits[:k]]
    if not relevant:
        return {f"hit_at_{k}": None, f"recall_at_{k}": None, f"precision_at_{k}": None, "mrr": None, f"ndcg_at_{k}": None}
    matched = relevant.intersection(ranked)
    first = next((index for index, name in enumerate(ranked, 1) if name in relevant), None)
    seen = set()
    dcg = 0.0
    for index, name in enumerate(ranked, 1):
        if name in relevant and name not in seen:
            dcg += 1.0 / math.log2(index + 1)
            seen.add(name)
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_count + 1))
    return {
        f"hit_at_{k}": float(bool(matched)),
        f"recall_at_{k}": len(matched) / max(1, len(relevant)),
        f"precision_at_{k}": len(matched) / max(1, k),
        "mrr": 1.0 / first if first else 0.0,
        f"ndcg_at_{k}": dcg / idcg if idcg else 0.0,
    }


def aggregate(rows: List[Dict[str, Any]], keys: Iterable[str]) -> Dict[str, float]:
    result = {}
    for key in keys:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        result[key] = sum(values) / len(values) if values else 0.0
    return result
