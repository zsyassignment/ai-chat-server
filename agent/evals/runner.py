#!/usr/bin/env python3
"""Evaluate vector recall, inverted recall, fused ranking, coverage, and latency."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from statistics import mean

from app.services.runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/datasets/sample.json")
    parser.add_argument("--user", default="eval")
    args = parser.parse_args()
    runtime = build_runtime()
    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    results = []
    try:
        for case in cases:
            started = time.perf_counter()
            retrieval = runtime.knowledge.search(args.user, case["question"], 10)
            latency = round((time.perf_counter() - started) * 1000, 2)
            diagnostics = retrieval.diagnostics or {}
            fused_rank = _rank(retrieval.hits, case["expected_document"])
            vector_rank = _rank(diagnostics.get("vector_candidates", []), case["expected_document"])
            keyword_rank = _rank(diagnostics.get("keyword_candidates", []), case["expected_document"])
            text = " ".join(hit["content"] for hit in retrieval.hits)
            terms = case.get("expected_terms", [])
            coverage = sum(term in text for term in terms) / max(1, len(terms))
            results.append({
                "id": case["id"],
                "mode": retrieval.mode,
                "fused_hit": fused_rank is not None,
                "fused_rank": fused_rank,
                "fused_rr": 1 / fused_rank if fused_rank else 0,
                "vector_hit": vector_rank is not None,
                "vector_rank": vector_rank,
                "keyword_hit": keyword_rank is not None,
                "keyword_rank": keyword_rank,
                "term_coverage": coverage,
                "latency_ms": latency,
                "vector_count": diagnostics.get("vector_count", 0),
                "keyword_count": diagnostics.get("keyword_count", 0),
                "fused_count": diagnostics.get("fused_count", 0),
                "reranker": diagnostics.get("reranker", "none"),
                "rewrite_recommended": retrieval.weak,
            })
        report = {
            "total": len(results),
            "vector_hit_at_k": _mean(results, "vector_hit"),
            "keyword_hit_at_k": _mean(results, "keyword_hit"),
            "fused_hit_at_10": _mean(results, "fused_hit"),
            "fused_mrr": _mean(results, "fused_rr"),
            "term_coverage": _mean(results, "term_coverage"),
            "avg_latency_ms": _mean(results, "latency_ms"),
            "rewrite_recommend_rate": _mean(results, "rewrite_recommended"),
            "results": results,
        }
        output = Path("evals/reports") / f"report-{int(time.time())}.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("saved:", output)
    finally:
        runtime.close()


def _rank(hits, expected_document):
    return next((index for index, hit in enumerate(hits, 1) if hit.get("filename") == expected_document), None)


def _mean(rows, key):
    return mean(float(row[key]) for row in rows) if rows else 0.0


if __name__ == "__main__":
    main()
