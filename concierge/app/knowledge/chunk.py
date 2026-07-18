"""Structure-first chunking.

Hospitality knowledge is mostly short facts — hours, "do you allow dogs?", a menu
section. Fixed-size windows would bury a one-line answer inside unrelated text and
blunt retrieval. So we split on structure (headings, blank-line paragraphs, list
runs) into small semantic units, and only pack a unit up toward a size cap when a
section is genuinely long. A heading is carried onto its section's chunks as a
`title`, which both helps the model and improves embedding relevance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Rough token estimate without a tokenizer dependency: ~4 chars/token.
_CHARS_PER_TOKEN = 4
MAX_CHUNK_TOKENS = 500
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * _CHARS_PER_TOKEN

_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")
# "Hours:", "Cancellation Policy —", a bare "PARKING" line, etc.
_LABEL_HEADING = re.compile(r"^\s{0,3}([A-Z][\w &/'-]{1,48})\s*[:—-]?\s*$")


@dataclass
class Chunk:
    title: str | None
    content: str


def _is_heading(line: str) -> str | None:
    if m := _MD_HEADING.match(line):
        return m.group(1).strip()
    if (m := _LABEL_HEADING.match(line)) and len(line.split()) <= 6:
        return m.group(1).strip()
    return None


def _flush(title: str | None, buf: list[str], out: list[Chunk]) -> None:
    text = "\n".join(buf).strip()
    if not text:
        return
    # Long section → pack into ≤ cap pieces on paragraph boundaries.
    if len(text) <= MAX_CHUNK_CHARS:
        out.append(Chunk(title=title, content=text))
        return
    piece: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        if size + len(para) > MAX_CHUNK_CHARS and piece:
            out.append(Chunk(title=title, content="\n\n".join(piece).strip()))
            piece, size = [], 0
        piece.append(para)
        size += len(para) + 2
    if piece:
        out.append(Chunk(title=title, content="\n\n".join(piece).strip()))


def chunk_document(text: str, *, base_title: str | None = None) -> list[Chunk]:
    """Split a document into small, titled, semantically-coherent chunks."""
    out: list[Chunk] = []
    title = base_title
    buf: list[str] = []

    for raw in text.replace("\r\n", "\n").split("\n"):
        heading = _is_heading(raw)
        if heading is not None:
            _flush(title, buf, out)
            buf = []
            title = heading if base_title is None else f"{base_title} — {heading}"
        else:
            buf.append(raw)
    _flush(title, buf, out)

    # Merge tiny orphan chunks (e.g. a lone heading line's stub) forward.
    merged: list[Chunk] = []
    for c in out:
        if merged and len(c.content) < 40 and merged[-1].title == c.title:
            merged[-1] = Chunk(merged[-1].title, f"{merged[-1].content}\n{c.content}")
        else:
            merged.append(c)
    return merged
