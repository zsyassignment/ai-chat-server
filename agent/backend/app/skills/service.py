"""Upload, validate, persist, match, and render declarative Agent Skills."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List

from app.core.ids import new_id, normalize_id

_ALLOWED_TOOLS = {
    "search_private_knowledge", "list_knowledge_documents", "search_web", "get_learning_plan",
    "update_learning_progress", "create_learning_reminder", "list_learning_reminders",
}
_ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
_MAX_FILES = 40
_MAX_UNCOMPRESSED = 2 * 1024 * 1024


class SkillService:
    """Manage data-only skills. Uploaded executable code is never accepted or imported."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def install_zip(self, user_id: str, filename: str, content: bytes) -> Dict[str, Any]:
        if not filename.lower().endswith(".zip"):
            raise ValueError("skill package must be a .zip file")
        if len(content) > _MAX_UNCOMPRESSED:
            raise ValueError("skill package exceeds 2 MB")
        import io

        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise ValueError("invalid skill zip archive") from exc
        with archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if not files or len(files) > _MAX_FILES:
                raise ValueError(f"skill package must contain 1-{_MAX_FILES} files")
            if sum(item.file_size for item in files) > _MAX_UNCOMPRESSED:
                raise ValueError("uncompressed skill package exceeds 2 MB")
            names = [_safe_member(item.filename) for item in files]
            prefix = _common_prefix(names)
            relative = [name.relative_to(prefix) if prefix.parts else name for name in names]
            if PurePosixPath("manifest.json") not in relative or PurePosixPath("SKILL.md") not in relative:
                raise ValueError("skill package requires manifest.json and SKILL.md")
            raw = archive.read(str(prefix / "manifest.json") if prefix.parts else "manifest.json")
            try:
                manifest = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("manifest.json must contain valid UTF-8 JSON") from exc
            validated = _validate_manifest(manifest)
            safe_user = normalize_id(user_id, "guest")
            skill_id = f"{normalize_id(validated['name'], 'skill')}-{normalize_id(validated['version'], 'v1')}"
            destination = self.root / safe_user / skill_id
            temporary = destination.with_name(f".{skill_id}-{new_id('install')}")
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir(parents=True)
            try:
                for item, path in zip(files, relative):
                    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                        raise ValueError(f"unsupported skill file: {path}")
                    target = temporary.joinpath(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
                _validate_references(temporary, validated)
                validated["enabled"] = True
                validated["skill_id"] = skill_id
                (temporary / "manifest.json").write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
                if destination.exists():
                    shutil.rmtree(destination)
                temporary.rename(destination)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return self.get(safe_user, skill_id) or {}

    def list(self, user_id: str) -> List[Dict[str, Any]]:
        directory = self.root / normalize_id(user_id, "guest")
        if not directory.exists():
            return []
        skills = [item for path in directory.iterdir() if path.is_dir() and (item := self._load(path))]
        return sorted(skills, key=lambda item: (item["name"], item["version"]))

    @staticmethod
    def public(skill: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in skill.items() if key != "path"}

    def get(self, user_id: str, skill_id: str) -> Dict[str, Any] | None:
        path = self.root / normalize_id(user_id, "guest") / normalize_id(skill_id, "skill")
        return self._load(path) if path.is_dir() else None

    def set_enabled(self, user_id: str, skill_id: str, enabled: bool) -> Dict[str, Any] | None:
        path = self.root / normalize_id(user_id, "guest") / normalize_id(skill_id, "skill")
        skill = self._load(path) if path.is_dir() else None
        if not skill:
            return None
        skill["enabled"] = bool(enabled)
        _write_manifest(path, skill)
        return self._load(path)

    def delete(self, user_id: str, skill_id: str) -> bool:
        path = self.root / normalize_id(user_id, "guest") / normalize_id(skill_id, "skill")
        if not path.is_dir():
            return False
        shutil.rmtree(path)
        return True

    def match(self, user_id: str, question: str) -> Dict[str, Any] | None:
        text = question.lower()
        candidates = []
        for skill in self.list(user_id):
            if not skill.get("enabled"):
                continue
            score = sum(len(trigger) for trigger in skill["triggers"] if trigger.lower() in text)
            if score:
                candidates.append((score, skill))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def render_context(self, skill: Dict[str, Any], max_chars: int = 12000) -> str:
        base = Path(skill["path"])
        sections = [f"# Skill: {skill['name']} v{skill['version']}", (base / "SKILL.md").read_text(encoding="utf-8")]
        for step in skill.get("workflow", []):
            sections.append(f"## Step: {step['id']}\n{step['instruction']}")
        for relative in skill.get("resources", []):
            sections.append(f"## Resource: {relative}\n{(base / relative).read_text(encoding='utf-8')}")
        schema = skill.get("output_schema")
        if schema:
            sections.append(f"## Required output JSON Schema\n{(base / schema).read_text(encoding='utf-8')}")
        return "\n\n".join(sections)[:max_chars]

    def _load(self, path: Path) -> Dict[str, Any] | None:
        try:
            manifest = _validate_manifest(json.loads((path / "manifest.json").read_text(encoding="utf-8")))
            _validate_references(path, manifest)
            return manifest | {"skill_id": path.name, "path": str(path), "enabled": bool(manifest.get("enabled", True))}
        except (OSError, ValueError, json.JSONDecodeError):
            return None


def _validate_manifest(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    name, version = str(value.get("name", "")).strip(), str(value.get("version", "")).strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,63}", name):
        raise ValueError("skill name must be 2-64 safe characters")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version):
        raise ValueError("skill version must look like 1 or 1.0.0")
    description = str(value.get("description", "")).strip()
    triggers = [str(item).strip() for item in value.get("triggers", []) if str(item).strip()]
    tools = list(dict.fromkeys(str(item) for item in value.get("allowed_tools", [])))
    if not description or not triggers:
        raise ValueError("description and at least one trigger are required")
    unknown = sorted(set(tools) - _ALLOWED_TOOLS)
    if unknown:
        raise ValueError(f"unsupported tools: {', '.join(unknown)}")
    workflow = value.get("workflow", [])
    if not isinstance(workflow, list) or len(workflow) > 20:
        raise ValueError("workflow must be a list with at most 20 steps")
    normalized_steps = []
    for index, step in enumerate(workflow, 1):
        if not isinstance(step, dict) or not str(step.get("instruction", "")).strip():
            raise ValueError("every workflow step requires an instruction")
        tool = str(step.get("tool", "")).strip()
        if tool and tool not in tools:
            raise ValueError(f"workflow tool is not allowlisted: {tool}")
        normalized_steps.append({"id": str(step.get("id") or f"step-{index}"), "instruction": str(step["instruction"])[:2000], "tool": tool})
    resources = [_safe_relative(str(item)) for item in value.get("resources", [])]
    output_schema = str(value.get("output_schema", "")).strip()
    if output_schema:
        _safe_relative(output_schema)
    return {
        "name": name, "version": version, "description": description[:500],
        "triggers": triggers[:30], "allowed_tools": tools,
        "workflow": normalized_steps, "resources": resources,
        "output_schema": output_schema, "enabled": bool(value.get("enabled", True)),
    }


def _validate_references(base: Path, manifest: Dict[str, Any]) -> None:
    for relative in ["SKILL.md", *manifest.get("resources", [])]:
        target = base / relative
        if not target.is_file() or target.stat().st_size > 512 * 1024:
            raise ValueError(f"missing or oversized skill file: {relative}")
    schema = manifest.get("output_schema")
    if schema:
        target = base / schema
        if not target.is_file():
            raise ValueError(f"missing output schema: {schema}")
        json.loads(target.read_text(encoding="utf-8"))


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(part.startswith(".") for part in path.parts):
        raise ValueError(f"unsafe skill path: {name}")
    if path.suffix.lower() in {".py", ".pyc", ".so", ".dll", ".exe", ".sh"}:
        raise ValueError("executable code is not allowed in uploaded skills")
    return path


def _safe_relative(name: str) -> str:
    path = _safe_member(name)
    return str(path)


def _common_prefix(paths: Iterable[PurePosixPath]) -> PurePosixPath:
    rows = list(paths)
    first = rows[0].parts[0]
    return PurePosixPath(first) if all(len(path.parts) > 1 and path.parts[0] == first for path in rows) else PurePosixPath()


def _write_manifest(path: Path, skill: Dict[str, Any]) -> None:
    clean = {key: value for key, value in skill.items() if key not in {"path", "skill_id"}}
    (path / "manifest.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
