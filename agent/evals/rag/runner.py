#!/usr/bin/env python3
"""Run controlled or mixed-corpus LearningFlow RAG benchmarks."""

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
from app.rag.store import reciprocal_rank_fusion
from app.services.agent_service import AgentService
from app.services.runtime import build_runtime
from evals.rag.metrics.generation import answer_metrics
from evals.rag.metrics.retrieval import aggregate, retrieval_metrics

ROOT = Path(__file__).resolve().parent
MODES = ("dense", "bm25", "hybrid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "benchmark.jsonl")
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus" / "documents.json")
    parser.add_argument("--corpus-profile", choices=["controlled", "mixed"], default="controlled")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--retrieval-mode", choices=[*MODES, "compare"], default="hybrid")
    parser.add_argument("--vector-weight", type=float, default=0.1)
    parser.add_argument("--keyword-weight", type=float, default=1.0)
    parser.add_argument("--end-to-end", action="store_true", help="also run Agent answer and citation/refusal metrics; hybrid mode only")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.end_to_end and args.retrieval_mode not in {"hybrid"}:
        parser.error("--end-to-end currently requires --retrieval-mode hybrid")
    report = run_benchmark(
        args.dataset, args.corpus, args.split, args.k, args.end_to_end,
        corpus_profile=args.corpus_profile, retrieval_mode=args.retrieval_mode,
        vector_weight=args.vector_weight, keyword_weight=args.keyword_weight,
    )
    output = args.output or ROOT / "reports" / f"report-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("saved:", output)


def run_benchmark(
    dataset: Path,
    corpus: Path,
    split: str = "test",
    k: int = 5,
    end_to_end: bool = False,
    *,
    corpus_profile: str = "controlled",
    retrieval_mode: str = "hybrid",
    vector_weight: float = 0.1,
    keyword_weight: float = 1.0,
) -> Dict[str, Any]:
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if split != "all":
        cases = [case for case in cases if case["split"] == split]
    documents = _load_corpus(corpus, corpus_profile)
    with tempfile.TemporaryDirectory(prefix="learningflow-eval-") as directory:
        base = Path(directory)
        settings = replace(
            Settings.from_env(), data_dir=base, database_path=base / "eval.db",
            checkpoint_path=base / "checkpoints.db", qdrant_path=base / "qdrant",
            skills_dir=base / "skills", require_plan_approval=False,
            llm_api_key="" if not end_to_end else Settings.from_env().llm_api_key,
        )
        runtime = build_runtime(settings)
        try:
            corpus_stats = _index_corpus(runtime, documents)
            if retrieval_mode == "compare":
                rows_by_mode = {mode: [] for mode in MODES}
                for case in cases:
                    for mode, row in _evaluate_case_comparison(
                        runtime, case, k, vector_weight, keyword_weight,
                    ).items():
                        rows_by_mode[mode].append(row)
            else:
                rows_by_mode = {
                    retrieval_mode: [
                        _evaluate_case(runtime, case, k, end_to_end, retrieval_mode)
                        for case in cases
                    ]
                }
        finally:
            runtime.close()

    mode_reports = {
        mode: _summarize(rows, split, k)
        for mode, rows in rows_by_mode.items()
    }
    summary: Dict[str, Any] = {
        "corpus_profile": corpus_profile,
        "corpus": corpus_stats,
        "retrieval_mode": retrieval_mode,
        "rrf_weights": {"vector": vector_weight, "keyword": keyword_weight},
        "total": len(cases),
        "split": split,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if retrieval_mode == "compare":
        summary["modes"] = {mode: report["summary"] for mode, report in mode_reports.items()}
        return {
            "summary": summary,
            "by_bucket": {mode: report["by_bucket"] for mode, report in mode_reports.items()},
            "cases": rows_by_mode,
        }
    report = mode_reports[retrieval_mode]
    summary.update(report["summary"])
    return {"summary": summary, "by_bucket": report["by_bucket"], "cases": rows_by_mode[retrieval_mode]}


def _load_corpus(corpus: Path, profile: str) -> List[Dict[str, Any]]:
    documents = json.loads(corpus.read_text(encoding="utf-8"))
    if profile == "controlled":
        return documents
    manifest = ROOT / "corpus" / "mixed_manifest.json"
    config = json.loads(manifest.read_text(encoding="utf-8"))
    for source in config["local_sources"]:
        pattern = str(source["glob"])
        prefix = str(source.get("filename_prefix", ""))
        for path in sorted(manifest.parent.glob(pattern)):
            # MDX is used only as a local benchmark source. The production
            # uploader intentionally keeps its narrower PDF/Markdown/TXT
            # allowlist, so expose MDX content to the splitter as Markdown.
            source_name = path.with_suffix(".md").name if path.suffix == ".mdx" else path.name
            documents.append({
                "filename": prefix + source_name,
                "content": path.read_text(encoding="utf-8"),
                "source": str(path),
            })
    filenames = [item["filename"] for item in documents]
    if len(filenames) != len(set(filenames)):
        raise ValueError("mixed corpus contains duplicate filenames")
    return documents


def _index_corpus(runtime, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_chunks = 0
    total_characters = 0
    started = time.perf_counter()
    for document in documents:
        content = document["content"].encode("utf-8")
        chunks = parse_document(document["filename"], content, chunk_size=500, overlap=80)
        saved = runtime.database.add_document("eval", document["filename"], "text/markdown", chunks)
        runtime.knowledge.index_document("eval", saved["id"])
        total_chunks += len(chunks)
        total_characters += len(document["content"])
    return {
        "documents": len(documents),
        "chunks": total_chunks,
        "characters": total_characters,
        "indexing_ms": (time.perf_counter() - started) * 1000,
    }


def _query_for_case(runtime, case: Dict[str, Any]) -> str:
    query = case.get("standalone_question") or case["question"]
    if case.get("history"):
        query = runtime.conversations.contextualize(case["question"], {}, case["history"])["standalone_question"]
    return query


def _evaluate_case(runtime, case: Dict[str, Any], k: int, end_to_end: bool, mode: str) -> Dict[str, Any]:
    query = _query_for_case(runtime, case)
    started = time.perf_counter()
    hits = _retrieve(runtime, query, k, mode)
    latency = (time.perf_counter() - started) * 1000
    row = _score_case(case, query, hits, k, latency, mode)
    if end_to_end:
        events = list(AgentService(runtime).run(
            user_id="eval", thread_id=f"eval-{case['id']}",
            question=f"根据资料回答：{query}", history=case.get("history", []),
        ))
        answer = events[-1]["data"].get("answer", "")
        row.update(answer_metrics(answer, case.get("expected_terms", []), len(hits), case["answerable"]))
        row["answer"] = answer
    return row


def _evaluate_case_comparison(
    runtime, case: Dict[str, Any], k: int,
    vector_weight: float = 1.0, keyword_weight: float = 1.0,
) -> Dict[str, Dict[str, Any]]:
    query = _query_for_case(runtime, case)
    started = time.perf_counter()
    keyword_rows = runtime.database.keyword_search("eval", query, runtime.settings.keyword_recall_k)
    keyword_ms = (time.perf_counter() - started) * 1000
    keyword_hits = [_row_to_hit(item, "keyword") for item in keyword_rows]

    started = time.perf_counter()
    vector_hits = runtime.knowledge._vector_search("eval", query, runtime.settings.vector_recall_k)
    vector_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    hybrid_hits = reciprocal_rank_fusion(
        {"vector": vector_hits, "keyword": keyword_hits}, rrf_k=runtime.settings.rrf_k,
        weights={"vector": vector_weight, "keyword": keyword_weight},
    )[:k]
    fusion_ms = (time.perf_counter() - started) * 1000
    return {
        "dense": _score_case(case, query, vector_hits[:k], k, vector_ms, "dense"),
        "bm25": _score_case(case, query, keyword_hits[:k], k, keyword_ms, "bm25"),
        "hybrid": _score_case(case, query, hybrid_hits, k, vector_ms + keyword_ms + fusion_ms, "hybrid"),
    }


def _retrieve(runtime, query: str, k: int, mode: str) -> List[Dict[str, Any]]:
    if mode == "dense":
        return runtime.knowledge._vector_search("eval", query, max(k, runtime.settings.vector_recall_k))[:k]
    if mode == "bm25":
        rows = runtime.database.keyword_search("eval", query, max(k, runtime.settings.keyword_recall_k))
        return [_row_to_hit(item, "keyword") for item in rows[:k]]
    return runtime.knowledge.search("eval", query, k).hits


def _row_to_hit(row: Dict[str, Any], path: str) -> Dict[str, Any]:
    return {
        "chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"],
        "chunk_index": int(row["chunk_index"]), "page": row.get("page"), "section": row.get("section", ""),
        "content": row["content"], "excerpt": row["content"][:360],
        "score": float(row.get("score", 0.0)), "retrieval_paths": [path],
    }


def _score_case(case: Dict[str, Any], query: str, hits: List[Dict[str, Any]], k: int, latency: float, mode: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": case["id"], "split": case["split"], "bucket": case["bucket"], "query": query,
        "answerable": case["answerable"], "mode": mode, "latency_ms": latency,
    }
    row.update(retrieval_metrics(hits, case.get("relevant_documents", []), k))
    text = " ".join(hit["content"] for hit in hits)
    terms = case.get("expected_terms", [])
    row["term_coverage"] = sum(term.lower() in text.lower() for term in terms) / len(terms) if terms else None
    row["negative_empty"] = float(not hits) if not case["answerable"] else None
    row["retrieved_documents"] = [hit["filename"] for hit in hits]
    return row


def _summarize(rows: List[Dict[str, Any]], split: str, k: int) -> Dict[str, Any]:
    metric_keys = [f"hit_at_{k}", f"recall_at_{k}", f"precision_at_{k}", "mrr", f"ndcg_at_{k}", "term_coverage", "negative_empty", "latency_ms"]
    buckets = sorted({row["bucket"] for row in rows})
    by_bucket = {bucket: aggregate([row for row in rows if row["bucket"] == bucket], metric_keys) for bucket in buckets}
    summary = aggregate(rows, metric_keys) | {
        "total": len(rows), "split": split, "bucket_counts": dict(Counter(row["bucket"] for row in rows)),
        "answerable_cases": sum(bool(row["answerable"]) for row in rows),
        "negative_cases": sum(not bool(row["answerable"]) for row in rows),
    }
    return {"summary": summary, "by_bucket": by_bucket}


if __name__ == "__main__":
    main()
