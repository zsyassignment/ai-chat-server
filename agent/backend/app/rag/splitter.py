"""Structure-aware PDF/Markdown parsing with recursive character splitting."""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

DEFAULT_SEPARATORS = [
    "\n# ", "\n## ", "\n### ", "\n#### ", "\n\n", "\n",
    "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ", ", " ", "",
]


def parse_document(
    filename: str,
    content: bytes,
    *,
    chunk_size: int = 800,
    overlap: int = 120,
) -> List[Dict[str, Any]]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"
    if suffix == "pdf":
        reader = PdfReader(io.BytesIO(content))
        pages = [
            {"text": page.extract_text() or "", "page": page_number}
            for page_number, page in enumerate(reader.pages, 1)
        ]
        return split_pages(pages, chunk_size=chunk_size, overlap=overlap)
    if suffix not in {"txt", "md", "markdown"}:
        raise ValueError("supported document types: .txt, .md, .pdf")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text documents must use UTF-8 encoding") from exc
    return split_pages(
        [{"text": text, "page": None}], chunk_size=chunk_size, overlap=overlap
    )


def split_pages(
    pages: List[Dict[str, Any]],
    chunk_size: int = 800,
    overlap: int = 120,
    separators: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Recursively split each page while preserving page and nearest heading.

    This uses LangChain's open-source RecursiveCharacterTextSplitter rather than
    a custom fixed-width loop. A title-aware pre-pass keeps section metadata.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
        separators=separators or DEFAULT_SEPARATORS,
        keep_separator=True,
        strip_whitespace=True,
    )
    chunks: List[Dict[str, Any]] = []
    for page in pages:
        normalized = re.sub(r"\r\n?", "\n", str(page.get("text", ""))).strip()
        if not normalized:
            continue
        sections = _section_blocks(normalized)
        for section, block in sections:
            for text in splitter.split_text(block):
                if text.strip():
                    chunks.append({"content": text.strip(), "page": page.get("page"), "section": section})
    return chunks


def _section_blocks(text: str) -> List[tuple[str, str]]:
    blocks: List[tuple[str, str]] = []
    section = ""
    buffer: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _looks_like_heading(stripped):
            if buffer and "\n".join(buffer).strip():
                blocks.append((section, "\n".join(buffer).strip()))
            section = stripped[:160]
            buffer = [stripped]
        else:
            buffer.append(line)
    if buffer and "\n".join(buffer).strip():
        blocks.append((section, "\n".join(buffer).strip()))
    return blocks or [("", text)]


def _looks_like_heading(text: str) -> bool:
    return bool(text) and len(text) <= 100 and bool(
        re.match(r"^(#{1,6}\s+|第[一二三四五六七八九十0-9]+[章节]|\d+(?:\.\d+)*[、.\s])", text)
    )
