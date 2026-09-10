"""Common graph-node helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from langgraph.config import get_stream_writer

from app.graph.context import GraphContext


def emit(event: str, node: str, **data: Any) -> None:
    try:
        get_stream_writer()({"event": event, "node": node, **data})
    except RuntimeError:
        pass


def recent_context(history: List[Dict[str, str]], limit: int = 8) -> str:
    return "\n".join(f"{item['role']}: {item['content']}" for item in history[-limit:])


def route_intent_rule(question: str) -> str:
    text = question.lower()
    if any(key in text for key in ("提醒我", "设置提醒", "创建提醒", "我的提醒", "查看提醒")): return "reminder"
    if any(key in text for key in ("完成第", "更新进度", "标记完成", "未完成")): return "update_progress"
    if any(key in text for key in ("学习计划", "学习路线", "怎么学", "制定计划", "安排一周")): return "create_plan"
    if any(key in text for key in ("出题", "测验", "测试我", "quiz", "练习题")): return "quiz"
    if any(key in text for key in ("学到哪里", "当前计划", "学习进度", "薄弱点", "错题")): return "progress"
    if any(key in text for key in ("深入研究", "深度研究", "调研", "研究报告")): return "deep_research"
    if any(key in text for key in ("联网", "网上搜索", "搜索网页", "查一下最新", "最近有什么更新", "最新消息", "最新进展", "近期新闻")): return "web_search"
    if any(key in text for key in ("根据资料", "知识库", "上传的", "文档", "教程", "论文")): return "knowledge_qa"
    return "chat"


def extract_topic(question: str) -> str:
    cleaned = re.sub(r"(?:请|帮我|根据资料|根据我上传的资料|制定|生成|学习计划|学习路线|出题|测验|深入研究|深度研究|调研|研究报告|一周|\d+天)", " ", question)
    return re.sub(r"\s+", " ", cleaned).strip(" ，。！？,.!?")[:100] or "当前学习主题"


def parse_days(question: str) -> int:
    match = re.search(r"(\d{1,2})\s*(?:天|日)", question)
    if match: return max(3, min(int(match.group(1)), 14))
    return 7


def parse_progress(question: str) -> tuple[int, bool]:
    match = re.search(r"第\s*(\d{1,2})\s*(?:天|日)", question)
    day = int(match.group(1)) if match else 0
    done = not any(word in question for word in ("取消", "未完成", "撤销"))
    return day, done


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
