"""rag layer implementation for chunker.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """Execute chunk_text at the chunker boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        text: Value supplied by the caller and validated by the surrounding schema.
        chunk_size: Value supplied by the caller and validated by the surrounding schema.
        overlap: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    normalized = " ".join((text or "").split())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_records(text: str, chunk_size: int = 500, overlap: int = 80) -> list[dict]:
    """Chunk source text while retaining offsets needed for evidence citations."""
    if not text or not text.strip():
        return []
    records: list[dict] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            records.append(
                {
                    "text": chunk,
                    "chunk_index": index,
                    "char_start": start,
                    "char_end": end,
                    "start_line": text.count("\n", 0, start) + 1,
                    "end_line": text.count("\n", 0, end) + 1,
                }
            )
            index += 1
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return records
