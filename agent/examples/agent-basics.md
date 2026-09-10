# Agent Loop

Agent Loop 是“决策、行动、观察”的有界循环。模型选择工具，工具返回 Observation，Observation 会成为下一轮决策的证据。工程实现必须有最大步骤数、重复调用检测、错误处理和结束条件。

# RAG

RAG 包括文档解析、文本分块、索引、查询检索、上下文注入和带来源生成。检索结果应当经过相关性判断；质量不足时可以重写查询并重试，但必须限制次数。

# LangGraph

LangGraph 使用 StateGraph、Node、Edge 和 Checkpointer 表示复杂 Agent 工作流。它适合条件分支、循环、人工中断、断点恢复和节点级流式事件。
