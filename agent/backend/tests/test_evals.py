from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.rag.metrics.generation import answer_metrics
from evals.rag.metrics.retrieval import retrieval_metrics
from evals.rag.runner import _load_corpus


def test_benchmark_has_100_balanced_cases_and_holdout_split():
    path = ROOT / "evals" / "rag" / "datasets" / "benchmark.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 100
    buckets = {name: [row for row in rows if row["bucket"] == name] for name in {
        "factual", "paraphrase", "multi_hop", "negative", "context_dependent",
    }}
    assert all(len(items) == 20 for items in buckets.values())
    assert sum(row["split"] == "dev" for row in rows) == 20
    assert sum(row["split"] == "test" for row in rows) == 80
    assert all(row["relevant_documents"] for row in rows if row["answerable"])
    assert all(not row["relevant_documents"] for row in rows if not row["answerable"])
    assert all(len(row["relevant_documents"]) >= 2 for row in rows if row["bucket"] == "multi_hop")
    assert all(row.get("standalone_question") for row in rows if row["bucket"] == "context_dependent")


def test_mixed_corpus_has_near_domain_and_public_domain_distractors():
    documents = _load_corpus(
        ROOT / "evals" / "rag" / "corpus" / "documents.json", "mixed"
    )
    names = {item["filename"] for item in documents}
    assert len(documents) >= 25
    assert any(name.startswith("near-tech-") for name in names)
    assert any(name.startswith("public-domain-") for name in names)


def test_retrieval_metric_definitions():
    hits = [{"filename": "wrong.md"}, {"filename": "right.md"}]
    scores = retrieval_metrics(hits, ["right.md", "also-right.md"], k=5)
    assert scores["hit_at_5"] == 1
    assert scores["recall_at_5"] == 0.5
    assert scores["precision_at_5"] == 0.2
    assert scores["mrr"] == 0.5
    assert 0 < scores["ndcg_at_5"] < 1
    assert retrieval_metrics(hits, [], k=5)["recall_at_5"] is None


def test_answer_metrics_cover_citations_and_refusal():
    grounded = answer_metrics("Observation 返回工具结果 [S1]", ["Observation", "工具结果"], 1, True)
    assert grounded["term_coverage"] == 1
    assert grounded["citation_accuracy"] == 1
    refused = answer_metrics("资料不足，无法回答。", [], 0, False)
    assert refused["refusal_correct"] == 1
