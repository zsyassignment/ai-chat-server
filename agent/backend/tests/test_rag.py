from __future__ import annotations

from app.rag.splitter import parse_document, split_pages


def test_markdown_split_preserves_heading():
    chunks = parse_document("guide.md", b"# Agent Loop\n\nDecision, Action, Observation.\n\n# RAG\n\nRetrieve then generate.")
    assert chunks
    assert any(chunk["section"] == "# Agent Loop" for chunk in chunks)


def test_fts_is_user_scoped(runtime):
    runtime.database.add_document("alice", "a.md", "text/markdown", [{"content": "Qdrant semantic retrieval", "section": "RAG"}])
    assert runtime.knowledge.search("alice", "Qdrant retrieval").hits
    assert runtime.knowledge.search("bob", "Qdrant retrieval").hits == []


def test_recursive_splitter_chunks_long_text_with_overlap_and_metadata():
    text = "# Long Section\n\n" + "Observation connects tool results to the next decision. " * 60
    chunks = split_pages([{"text": text, "page": 7}], chunk_size=220, overlap=40)
    assert len(chunks) > 2
    assert all(len(chunk["content"]) <= 220 for chunk in chunks)
    assert all(chunk["page"] == 7 for chunk in chunks)
    assert all(chunk["section"] == "# Long Section" for chunk in chunks)
    # Recursive splitter should retain overlap between adjacent chunks.
    assert any(left["content"][-20:] in right["content"] for left, right in zip(chunks, chunks[1:]))


def test_rrf_fuses_vector_and_keyword_without_raw_score_comparison():
    from app.rag.store import reciprocal_rank_fusion
    base = lambda chunk_id, score, path: {
        "chunk_id": chunk_id, "document_id": "d", "filename": "x.md",
        "chunk_index": 0, "page": None, "section": "", "content": chunk_id,
        "excerpt": chunk_id, "score": score, "retrieval_paths": [path],
    }
    fused = reciprocal_rank_fusion({
        "vector": [base("both", 0.51, "vector"), base("vector-only", 0.99, "vector")],
        "keyword": [base("both", 0.01, "keyword"), base("keyword-only", 99.0, "keyword")],
    }, rrf_k=60)
    assert fused[0]["chunk_id"] == "both"
    assert fused[0]["retrieval_paths"] == ["keyword", "vector"]


def test_rrf_weights_can_make_keyword_precision_primary():
    from app.rag.store import reciprocal_rank_fusion
    base = lambda chunk_id, path: {
        "chunk_id": chunk_id, "document_id": "d", "filename": "x.md",
        "chunk_index": 0, "page": None, "section": "", "content": chunk_id,
        "excerpt": chunk_id, "score": 1.0, "retrieval_paths": [path],
    }
    fused = reciprocal_rank_fusion({
        "vector": [base("vector-only", "vector")],
        "keyword": [base("keyword-only", "keyword")],
    }, rrf_k=60, weights={"vector": 0.1, "keyword": 1.0})
    assert [item["chunk_id"] for item in fused] == ["keyword-only", "vector-only"]


def test_hybrid_retrieval_uses_both_paths_and_returns_diagnostics(runtime):
    from app.llm.client import EmbeddingClient

    class FakeEmbeddings:
        enabled = True
        def embed(self, texts):
            return [[1.0, float("rag" in text.lower()), 0.5] for text in texts]

    runtime.knowledge.embeddings = FakeEmbeddings()
    document = runtime.database.add_document(
        "alice", "hybrid.md", "text/markdown",
        [{"content": "RAG combines semantic vector retrieval and keyword inverted indexes.", "section": "Hybrid"}],
    )
    runtime.knowledge.index_document("alice", document["id"])
    result = runtime.knowledge.search("alice", "RAG vector keyword")
    assert result.mode == "hybrid_rrf"
    assert result.hits
    assert set(result.hits[0]["retrieval_paths"]) == {"keyword", "vector"}
    assert result.diagnostics["vector_count"] >= 1
    assert result.diagnostics["keyword_count"] >= 1
    assert result.diagnostics["rrf_weights"] == {"vector": 0.1, "keyword": 1.0}


def test_fastembed_provider_is_lazy_and_returns_float_vectors(settings, monkeypatch):
    import sys
    from dataclasses import replace
    from types import SimpleNamespace
    from app.llm.client import EmbeddingClient

    class Vector:
        def tolist(self):
            return [0.1, 0.2, 0.3]

    class FakeTextEmbedding:
        def __init__(self, model_name, cache_dir, local_files_only=False):
            assert model_name == "BAAI/bge-small-zh-v1.5"

        def embed(self, texts):
            return [Vector() for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=FakeTextEmbedding))
    client = EmbeddingClient(replace(
        settings, embedding_provider="fastembed",
        embedding_model="BAAI/bge-small-zh-v1.5",
    ))
    assert client.enabled is True
    assert client.provider == "fastembed"
    assert client.embed(["中文", "RAG"]) == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]


def test_enabled_reranker_falls_back_when_optional_dependency_missing(settings, runtime):
    from dataclasses import replace
    from app.rag.reranker import Reranker
    configured = replace(settings, reranker_enabled=True)
    reranker = Reranker(configured)
    hits = [{"chunk_id": "a", "content": "Agent Loop", "rrf_score": 0.1}]
    ranked, mode = reranker.rerank("Agent", hits, 1)
    assert ranked == hits
    assert mode == "fallback"
    assert "sentence-transformers" in reranker.last_error


def test_fts_chinese_bigram_recall(runtime):
    runtime.database.add_document(
        "alice", "cn.md", "text/markdown",
        [{"content": "系统通过语义检索找到相关资料并生成答案", "section": "知识库"}],
    )
    hits = runtime.database.keyword_search("alice", "相关资料", 5)
    assert hits
    assert hits[0]["filename"] == "cn.md"


def test_reranker_reorders_candidates_with_cross_encoder_scores(settings):
    from dataclasses import replace
    from app.rag.reranker import Reranker

    class FakeCrossEncoder:
        def predict(self, pairs, show_progress_bar=False):
            return [0.1, 0.9]

    reranker = Reranker(replace(settings, reranker_enabled=True, reranker_top_n=2))
    reranker._model = FakeCrossEncoder()
    hits = [
        {"chunk_id": "first", "content": "weak", "rrf_score": 0.03},
        {"chunk_id": "second", "content": "strong", "rrf_score": 0.02},
    ]
    ranked, mode = reranker.rerank("query", hits, 2)
    assert mode == "cross_encoder"
    assert [item["chunk_id"] for item in ranked] == ["second", "first"]


def test_chunk_overlap_is_clamped_below_chunk_size(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("CHUNK_SIZE", "200")
    monkeypatch.setenv("CHUNK_OVERLAP", "999")
    settings = Settings.from_env()
    assert settings.chunk_size == 200
    assert settings.chunk_overlap == 199
