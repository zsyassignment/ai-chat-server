"""Reference-based answer metrics that do not hide behind a subjective score."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable


def answer_metrics(answer: str, expected_terms: Iterable[str], source_count: int, answerable: bool) -> Dict[str, float]:
    terms = list(expected_terms)
    coverage = sum(term.lower() in answer.lower() for term in terms) / max(1, len(terms))
    citations = [int(value) for value in re.findall(r"\[(?:S|W)(\d+)\]", answer)]
    valid = sum(1 <= number <= source_count for number in citations)
    refusal = any(term in answer for term in ("没有足够", "无法回答", "资料不足", "未找到"))
    return {
        "term_coverage": coverage,
        "citation_accuracy": valid / max(1, len(citations)) if citations else (0.0 if answerable else 1.0),
        "refusal_correct": float(refusal != answerable),
    }
