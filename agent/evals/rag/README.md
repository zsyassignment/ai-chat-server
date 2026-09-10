# LearningFlow RAG Benchmark

## 数据集

固定 100 题，5 类各 20 题；每类前 4 题组成 `dev`，其余 16 题组成
`test`。RRF 权重只能在 20 题开发集上选择，最终结果报告 80 题测试集。

| Bucket | 评测目标 |
|---|---|
| `factual` | 单文档事实召回 |
| `paraphrase` | 查询与文档措辞不同的语义泛化 |
| `multi_hop` | 每题标注 2～3 篇相关文档，检查多证据召回 |
| `negative` | 知识库无答案；检索层与最终拒答需分开评估 |
| `context_dependent` | 使用人工标注的独立问题，确定性评估上下文改写后的检索 |

## 两种语料规模

- `controlled`：10 篇目标技术短文、10 个 Chunk，用于快速单元回归。
- `mixed`：10 篇目标文档 + 38 篇 BotMux 中文技术文档 + 3 部公版中文小说节选；
  当前共 51 篇、约 34.6 万字符、1151 个 Chunk。来源见
  [`corpus/SOURCES.md`](corpus/SOURCES.md)。

混合语料同时包含同领域技术干扰和跨领域文学噪声，比原 10-Chunk 语料更接近真实知识库。

## 运行

快速回归：

```bash
PYTHONPATH=backend .venv/bin/python -m evals.rag.runner \
  --corpus-profile controlled --split test --k 5
```

Dense、BM25 与加权 Hybrid 对照：

```bash
PYTHONPATH=backend .venv/bin/python -m evals.rag.runner \
  --corpus-profile mixed --split test --k 5 --retrieval-mode compare \
  --vector-weight 0.1 --keyword-weight 1.0
```

默认在临时目录重建 SQLite/Qdrant 索引，不污染应用数据。报告包括 Hit@5、
Recall@5、Precision@5、MRR、NDCG@5、关键词覆盖率和延迟。负样本的
`negative_empty` 只表示检索器是否返回空结果，不能冒充最终 Agent 拒答准确率。

`--end-to-end` 会调用 Agent 回答并评估引用与拒答，可能触发外部 LLM 调用；仅支持
`--retrieval-mode hybrid`。

## 当前基线

本地 `BAAI/bge-small-zh-v1.5`，Reranker 关闭；RRF 权重在开发集选择为
`vector=0.1, keyword=1.0`。固定测试集结果保存在
[`baselines/mixed-test-k5.json`](baselines/mixed-test-k5.json)。

测试集包含 80 题，其中 64 题可回答、16 题为负样本；检索指标仅对可回答题
求平均：

| 模式 | Hit@5 | Recall@5 | MRR | NDCG@5 | 平均延迟 |
|---|---:|---:|---:|---:|---:|
| Dense | 64.06% | 53.39% | 53.57% | 48.43% | 304.10 ms |
| BM25 | 82.81% | 79.69% | 75.00% | 73.72% | 4.77 ms |
| Hybrid RRF | **84.38%** | **80.47%** | **76.82%** | **75.13%** | 308.95 ms |

开发集表明当前本地小模型在大量相近技术文本中更适合作为补召回信号，因此没有
使用等权 RRF。锁定 `0.1:1.0` 后，Hybrid 在未参与调参的测试集上相较 BM25 的
Hit@5、Recall@5、MRR、NDCG@5 均有小幅提升。Dense 的延迟包含本地 ONNX 查询编码；
BM25 为 SQLite FTS5 查询。

三种检索模式在 16 道负样本上都会返回某些最近邻，因此 `negative_empty=0`。
这证明“检索器返回候选”不能等同于“证据充分”，最终拒答应由 Agent 的证据评分和
置信度闸门决定；本表不宣称端到端拒答准确率。
