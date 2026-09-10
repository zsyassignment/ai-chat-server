# LearningFlow RAG Benchmark

100 个固定评测问题，5 个桶各 20 题；每桶前 4 题为开发集，其余为测试集。

| Bucket | Purpose |
|---|---|
| `factual` | 单文档事实召回 |
| `paraphrase` | 查询与文档措辞不同 |
| `multi_hop` | 多概念/多证据问题 |
| `negative` | 无答案与拒答 |
| `context_dependent` | 多轮上下文及指代消解 |

运行：

```bash
PYTHONPATH=backend .venv/bin/python -m evals.rag.runner --split test --k 5
PYTHONPATH=backend .venv/bin/python -m evals.rag.runner --split dev --k 5 --end-to-end
```

默认在临时目录中重建评测索引，不污染应用数据。报告按桶和整体输出 `Hit@5`、`Recall@5`、`Precision@5`、MRR、NDCG@5、关键词覆盖率、拒答准确率和延迟。`--end-to-end` 额外执行 Agent 回答并计算引用准确率。
