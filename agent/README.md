# Embedded LearningFlow Agent

本目录是随 C++ 网关一起发布的 LangGraph Agent 核心，来源于
[`zsyassignment/easy-agent`](https://github.com/zsyassignment/easy-agent)。

C++ 网关通过 `http://127.0.0.1:8010` 调用这里的 FastAPI/SSE 服务。该嵌入版保留
LangGraph 工作流、深度研究循环、混合 RAG、会话记忆、Skill、MCP、提醒和评测；
BotMux/飞书渠道适配只在独立的 `easy-agent` 仓库维护，避免 C++ 版本引入无关依赖。

开发测试：

```bash
PYTHONPATH=agent/backend agent/.venv/bin/python -m pytest agent/backend/tests
```
