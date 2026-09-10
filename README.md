# AI Chat Server：C++ 高并发网关 + LangGraph Agent

一个可以独立部署的完整对话式 Agent 项目：浏览器只访问 C++17 HTTP/SSE 网关，
网关将统一自然语言请求转发给仓库内置的 Python LangGraph Agent。用户无需手动切换
“普通对话/Agent 模式”，系统会自动判断闲聊、私有知识问答、联网搜索、学习计划、
进度、提醒、测验或深度研究。

## 架构

```text
Browser
  │ HTTP / SSE :9856
  ▼
C++17 Gateway
  ├─ Reactor + epoll + I/O threads
  ├─ worker pool + async logging + memory pool + LFU
  ├─ static Web UI
  ├─ POST /api/chat/direct ─────────────► OpenAI-compatible Chat API
  └─ /api/* transparent proxy
               │ HTTP / SSE :8010
               ▼
        Embedded LangGraph Agent
          ├─ intent routing + workflow
          ├─ Reason → Tool → Observation → Critic loop
          ├─ Qdrant Dense + SQLite FTS5/BM25 + RRF
          ├─ optional Cross-Encoder reranker
          ├─ rolling-summary conversation memory
          ├─ declarative Skills + MCP server
          └─ reminders + checkpoint + run trace
```

## 核心能力

### C++ 网关

- 主从 Reactor、epoll、多 I/O 线程和业务线程池
- HTTP/1.1 解析、Keep-Alive、Chunked Encoding 和 SSE 透传
- libcurl 上游客户端，支持 JSON 与 multipart 请求透明转发
- 自研内存池、LFU 缓存和双缓冲异步日志
- 一个公共 Origin：浏览器不需要知道 Python 服务端口
- 保留 `POST /api/chat/direct`，可单独展示原生 C++ 大模型流式链路

### 内置 LangGraph Agent

- LangGraph 状态图、条件路由、并行研究任务、Checkpoint 和 Interrupt/Resume
- 深度研究 Agent Loop：Reason → Tool → Observation → Critic，带轮次/工具预算和重复调用去重
- 混合 RAG：递归字符切分、FastEmbed BGE、Qdrant 稠密召回、FTS5/BM25 倒排召回、RRF 融合及可选精排
- 查询重写、证据质量评估、置信度闸门、本地不足时可选 Tavily 联网补充
- 近期原文窗口 + 结构化滚动摘要，支持长对话和上下文补全
- PDF、Markdown、TXT 文档上传；声明式 Skill 上传与工具白名单
- FastMCP 工具服务、APScheduler 持久化提醒、SQLite 长期数据和运行轨迹
- 51 篇、1151 Chunk 混合语料上的 100 题、5 类 RAG 评测集

Agent 的独立发布版（含 BotMux/飞书接入）位于：
[`zsyassignment/easy-agent`](https://github.com/zsyassignment/easy-agent)。

## 目录

```text
.
├── src/ + include/       # C++ 网络、HTTP、AI 和 AgentClient
├── memory/ + log/        # 内存池、缓存、异步日志
├── www/                  # 统一自然语言 Web 前端
├── agent/                # 完整 LangGraph Agent
│   ├── backend/          # FastAPI、Graph、RAG、Memory、MCP、Skill、提醒
│   ├── evals/rag/        # 100 题检索/生成评测
│   └── examples/         # 示例资料与 Skill
└── scripts/              # 环境安装和双服务启动
```

## 快速开始

要求：Linux、Python 3.11+、CMake 3.11+、C++17 编译器、libcurl 开发库。

```bash
git clone https://github.com/zsyassignment/ai-chat-server.git
cd ai-chat-server
cp .env.example .env

# 创建 Python venv、安装 Agent 依赖并构建 C++
bash scripts/setup-all.sh

# 同时启动内置 Agent :8010 与 C++ 网关 :9856
bash scripts/start-dev.sh
```

浏览器打开：

```text
http://127.0.0.1:9856
```

首次使用默认本地 Embedding 时会下载 `BAAI/bge-small-zh-v1.5` ONNX 模型。
未填写 `LLM_API_KEY` 时仍可运行离线规则流程；配置 OpenAI-compatible Chat API 后启用
完整模型路由、回答和 Function Calling。联网搜索需要额外填写 `TAVILY_API_KEY`。

也可以分步执行：

```bash
bash scripts/setup-agent.sh  # 只安装 Python Agent
bash setup.sh                # 只构建 C++
```

## 统一 API

| 网关接口 | 说明 | 上游 |
|---|---|---|
| `POST /api/chat` | 默认对话入口，SSE 返回 Agent 过程与答案 | `/api/chat/stream` |
| `POST /api/runs/resume` | 恢复计划确认等 Human-in-the-loop 中断 | 同名 Agent API |
| `/api/documents*` | 文档上传、列表、删除 | 透明代理 |
| `/api/reminders*` | 创建、查询、取消提醒 | 透明代理 |
| `/api/notifications*` | 站内通知 | 透明代理 |
| `/api/skills*` | Skill 上传、启停、删除 | 透明代理 |
| `/api/learning/plan` | 当前学习计划 | 透明代理 |
| `/api/health` | Agent、RAG、MCP 能力状态 | 透明代理 |
| `POST /api/chat/direct` | 仅使用原始 C++ → LLM 流式链路 | OpenAI-compatible API |

C++ 不解析 Agent 的 SSE 业务事件，仅做 HTTP Chunked 传输和字节级流式转发，因此
LangGraph 新增节点或事件时不需要修改网关。

## 配置重点

```env
AGENT_SERVICE_URL=http://127.0.0.1:8010
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com/v1/chat/completions
LLM_MODEL=deepseek-chat

EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
QDRANT_MODE=local

# 可选
TAVILY_API_KEY=tvly-...
RERANKER_ENABLED=false
```

完整参数见 [`.env.example`](.env.example)。`.env`、模型、数据库、向量索引、上传文件、
虚拟环境和构建产物均被 Git 忽略。

## 测试

```bash
# 内嵌 Agent
PYTHONPATH=agent/backend agent/.venv/bin/python -m pytest agent/backend/tests

# 前端语法
node --check www/main.js

# C++ 完整构建
bash setup.sh
```

独立 RAG 评测：

```bash
PYTHONPATH=agent/backend agent/.venv/bin/python -m agent.evals.rag.runner --split dev --k 5
```

## License

沿用原 C++ 项目的许可证，见 [LICENSE](LICENSE)。内嵌 Agent 来源及其依赖声明见
[`agent/README.md`](agent/README.md) 和独立仓库。
