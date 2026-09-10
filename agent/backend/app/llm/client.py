"""Small OpenAI-compatible clients for chat and embeddings."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import Settings
from app.core.json_utils import parse_json_object


class ChatClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._temperature_supported: bool | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key)

    def complete(self, messages: List[Dict[str, str]], *, temperature: float = 0.2, max_tokens: int = 1800) -> Optional[str]:
        if not self.enabled:
            return None
        payload = {"model": self.settings.llm_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        try:
            response = self._post_chat(payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return str(content).strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

    def complete_json(self, system: str, user_payload: Dict[str, Any], *, max_tokens: int = 1000) -> Optional[Dict[str, Any]]:
        text = self.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return parse_json_object(text) if text else None

    def complete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        max_tokens: int = 1200,
    ) -> Optional[Dict[str, Any]]:
        """Call an OpenAI-compatible model with native function tools."""
        if not self.enabled:
            return None
        payload = {
            "model": self.settings.llm_model,
            "messages": [_tool_wire_message(message) for message in messages],
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            response = self._post_chat(payload)
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            calls = []
            for raw in message.get("tool_calls") or []:
                function = raw.get("function") or {}
                arguments = function.get("arguments") or "{}"
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                calls.append({
                    "id": str(raw.get("id") or f"call_{len(calls) + 1}"),
                    "name": str(function.get("name") or ""),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                })
            return {"content": str(message.get("content") or "").strip(), "tool_calls": calls}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

    def _post_chat(self, payload: Dict[str, Any]) -> httpx.Response:
        """Retry once without temperature when a compatible API rejects it."""
        if self._temperature_supported is False and "temperature" in payload:
            payload = dict(payload)
            payload.pop("temperature", None)
        response = httpx.post(
            self.settings.llm_base_url,
            json=payload,
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            timeout=self.settings.llm_timeout,
        )
        if response.status_code == 400 and "temperature" in payload:
            try:
                error = response.json().get("error", {})
            except (json.JSONDecodeError, TypeError):
                error = {}
            if error.get("param") == "temperature" or "temperature" in str(error.get("message", "")).lower():
                self._temperature_supported = False
                compatible = dict(payload)
                compatible.pop("temperature", None)
                response = httpx.post(
                    self.settings.llm_base_url,
                    json=compatible,
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    timeout=self.settings.llm_timeout,
                )
        return response


def _tool_wire_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Convert normalized ReAct messages to OpenAI-compatible wire messages."""
    result = {
        key: message[key]
        for key in ("role", "content", "name", "tool_call_id")
        if key in message
    }
    if message.get("tool_calls"):
        result["tool_calls"] = [
            {
                "id": str(call.get("id", "")),
                "type": "function",
                "function": {
                    "name": str(call.get("name", "")),
                    "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                },
            }
            for call in message["tool_calls"]
        ]
    return result


class EmbeddingClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Any = None
        self.last_error = ""

    @property
    def enabled(self) -> bool:
        if self.settings.embedding_provider == "fastembed":
            return bool(self.settings.embedding_model)
        return bool(self.settings.embedding_provider == "openai" and self.settings.embedding_api_key and self.settings.embedding_model)

    @property
    def provider(self) -> str:
        return self.settings.embedding_provider

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts or not self.enabled:
            return []
        if self.settings.embedding_provider == "fastembed":
            try:
                if self._model is None:
                    from fastembed import TextEmbedding

                    # FastEmbed's legacy Qdrant archive uses fast-<model-name>.
                    # Once cached, force offline loading to avoid a Hugging Face
                    # metadata request on every process start.
                    local_dir = self.settings.embedding_cache_dir / f"fast-{self.settings.embedding_model.rsplit('/', 1)[-1]}"
                    self._model = TextEmbedding(
                        model_name=self.settings.embedding_model,
                        cache_dir=str(self.settings.embedding_cache_dir),
                        local_files_only=local_dir.is_dir(),
                    )
                vectors = [vector.tolist() for vector in self._model.embed(texts)]
                self.last_error = ""
                return [[float(value) for value in vector] for vector in vectors]
            except Exception as exc:
                self.last_error = str(exc)
                raise
        if self.settings.embedding_provider != "openai":
            raise ValueError(f"unknown embedding provider: {self.settings.embedding_provider}")
        vectors: List[List[float]] = []
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            response = httpx.post(
                self.settings.embedding_base_url,
                json={"model": self.settings.embedding_model, "input": batch},
                headers={"Authorization": f"Bearer {self.settings.embedding_api_key}"},
                timeout=self.settings.embedding_timeout,
            )
            response.raise_for_status()
            items = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors.extend([[float(value) for value in item["embedding"]] for item in items])
        if len(vectors) != len(texts) or len({len(vector) for vector in vectors}) != 1:
            raise ValueError("embedding API returned invalid vectors")
        self.last_error = ""
        return vectors
