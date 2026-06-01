from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
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

