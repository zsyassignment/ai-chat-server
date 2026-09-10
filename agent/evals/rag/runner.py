#!/usr/bin/env python3
"""Run the 100-case, five-bucket LearningFlow RAG benchmark."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import Settings
from app.rag.splitter import parse_document
from app.services.agent_service import AgentService
from app.services.runtime import build_runtime
from evals.rag.metrics.generation import answer_metrics
from evals.rag.metrics.retrieval import aggregate, retrieval_metrics

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "benchmark.jsonl")
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus" / "documents.json")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--end-to-end", action="store_true", help="also run Agent answer and citation/refusal metrics")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.dataset, args.corpus, args.split, args.k, args.end_to_end)
    output = args.output or ROOT / "reports" / f"report-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("saved:", output)


def run_benchmark(dataset: Path, corpus: Path, split: str = "test", k: int = 5, end_to_end: bool = False) -> Dict[str, Any]:
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if split != "all":
        cases = [case for case in cases if case["split"] == split]
    documents = json.loads(corpus.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="learningflow-eval-") as directory:
        base = Path(directory)
        settings = replace(
            Settings.from_env(), data_dir=base, database_path=base / "eval.db",
            checkpoint_path=base / "checkpoints.db", qdrant_path=base / "qdrant",
            skills_dir=base / "skills", require_plan_approval=False,
        )
        runtime = build_runtime(settings)
        try:
            _index_corpus(runtime, documents)
            rows = [_evaluate_case(runtime, case, k, end_to_end) for case in cases]
        finally:
            runtime.close()
    metric_keys = [f"hit_at_{k}", f"recall_at_{k}", f"precision_at_{k}", "mrr", f"ndcg_at_{k}", "term_coverage", "refusal_correct", "latency_ms"]
    by_bucket = {bucket: aggregate([row for row in rows if row["bucket"] == bucket], metric_keys) for bucket in sorted({row["bucket"] for row in rows})}
    summary = aggregate(rows, metric_keys) | {
        "total": len(rows), "split": split, "bucket_counts": dict(Counter(row["bucket"] for row in rows)),
        "answerable_cases": sum(bool(row["answerable"]) for row in rows),
        "negative_cases": sum(not bool(row["answerable"]) for row in rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"summary": summary, "by_bucket": by_bucket, "cases": rows}


def _index_corpus(runtime, documents: List[Dict[str, Any]]) -> None:
    for document in documents:
        content = document["content"].encode("utf-8")
        chunks = parse_document(document["filename"], content, chunk_size=500, overlap=80)
        saved = runtime.database.add_document("eval", document["filename"], "text/markdown", chunks)
        runtime.knowledge.index_document("eval", saved["id"])


def _evaluate_case(runtime, case: Dict[str, Any], k: int, end_to_end: bool) -> Dict[str, Any]:
    query = case.get("standalone_question") or case["question"]
    if case.get("history"):
        query = runtime.conversations.contextualize(case["question"], {}, case["history"])["standalone_question"]
    started = time.perf_counter()
    retrieval = runtime.knowledge.search("eval", query, k)
    latency = (time.perf_counter() - started) * 1000
    row = {"id": case["id"], "split": case["split"], "bucket": case["bucket"], "query": query, "answerable": case["answerable"], "mode": retrieval.mode, "latency_ms": latency}
    row.update(retrieval_metrics(retrieval.hits, case.get("relevant_documents", []), k))
    text = " ".join(hit["content"] for hit in retrieval.hits)
    terms = case.get("expected_terms", [])
    row["term_coverage"] = sum(term.lower() in text.lower() for term in terms) / len(terms) if terms else None
    row["refusal_correct"] = float((not retrieval.hits) == (not case["answerable"]))
    row["retrieved_documents"] = [hit["filename"] for hit in retrieval.hits]
    if end_to_end:
        events = list(AgentService(runtime).run(user_id="eval", thread_id=f"eval-{case['id']}", question=f"根据资料回答：{query}", history=case.get("history", [])))
        answer = events[-1]["data"].get("answer", "")
        row.update(answer_metrics(answer, case.get("expected_terms", []), len(retrieval.hits), case["answerable"]))
        row["answer"] = answer
    return row


if __name__ == "__main__":
    main()
