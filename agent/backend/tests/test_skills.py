from __future__ import annotations

import io
import json
import zipfile
from app.skills.service import SkillService
from app.graph.nodes.workflow import _research_tool_schemas


def skill_zip(manifest=None, extra=None):
    manifest = manifest or {
        "name": "paper-review",
        "version": "1.0.0",
        "description": "Review papers with private and public evidence",
        "triggers": ["论文精读", "分析论文"],
        "allowed_tools": ["search_private_knowledge", "list_knowledge_documents", "search_web"],
        "workflow": [
            {"id": "extract", "instruction": "提取研究问题、方法和贡献", "tool": "search_private_knowledge"},
            {"id": "compare", "instruction": "联网检索相关工作", "tool": "search_web"},
        ],
        "resources": ["resources/checklist.md"],
        "output_schema": "schemas/report.json",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("paper-review/manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("paper-review/SKILL.md", "# Paper Review\n\nEvidence first; compare methods and limitations.")
        archive.writestr("paper-review/resources/checklist.md", "Check baselines, ablations, limits, and reproducibility.")
        archive.writestr("paper-review/schemas/report.json", json.dumps({"type": "object"}))
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def test_skill_install_match_toggle_and_delete(tmp_path):
    service = SkillService(tmp_path / "skills")
    installed = service.install_zip("alice", "paper-review.zip", skill_zip())
    assert installed["skill_id"] == "paper-review-1.0.0"
    assert service.match("alice", "请帮我论文精读") ["name"] == "paper-review"
    assert "Evidence first" in service.render_context(installed)
    assert "Check baselines" in service.render_context(installed)
    assert "Required output JSON Schema" in service.render_context(installed)
    assert {item["function"]["name"] for item in _research_tool_schemas(installed, web_enabled=True)} == {
        "search_private_knowledge", "list_knowledge_documents", "search_web",
    }

    assert service.set_enabled("alice", installed["skill_id"], False)["enabled"] is False
    assert service.match("alice", "请帮我论文精读") is None
    assert service.delete("alice", installed["skill_id"]) is True


def test_skill_upload_rejects_code_traversal_and_unknown_tools(tmp_path):
    service = SkillService(tmp_path / "skills")
    try:
        service.install_zip("alice", "bad.zip", skill_zip(extra={"paper-review/run.py": "print('unsafe')"}))
        raise AssertionError("Python upload should be rejected")
    except ValueError as exc:
        assert "executable code" in str(exc)

    bad = {
        "name": "unsafe-skill", "version": "1.0.0", "description": "bad",
        "triggers": ["bad"], "allowed_tools": ["run_shell"], "workflow": [],
    }
    try:
        service.install_zip("alice", "bad.zip", skill_zip(manifest=bad))
        raise AssertionError("unknown tool should be rejected")
    except ValueError as exc:
        assert "unsupported tools" in str(exc)


def test_skill_api_and_graph_auto_activation(runtime, settings):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import build_router
    from app.services.agent_service import AgentService

    app = FastAPI()
    app.include_router(build_router(runtime))
    client = TestClient(app)
    response = client.post(
        "/api/skills", data={"user_id": "alice"},
        files={"file": ("paper-review.zip", skill_zip(), "application/zip")},
    )
    assert response.status_code == 200
    skill = response.json()["skill"]
    assert client.get("/api/skills", params={"user_id": "alice"}).json()["skills"]

    events = list(AgentService(runtime).run(
        user_id="alice", thread_id="skill-thread", question="请分析论文中的 RAG 方法"
    ))
    loaded = next(item for item in events if item["event"] == "node_status")
    assert loaded["data"]["skill"] == "paper-review"
    assert events[-1]["data"]["intent"] == "deep_research"

    disabled = client.patch(f"/api/skills/{skill['skill_id']}", json={"user_id": "alice", "enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["skill"]["enabled"] is False
