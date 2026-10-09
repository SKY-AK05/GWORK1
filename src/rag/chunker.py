"""Text chunker for RAG context engineering."""

from __future__ import annotations

from typing import List


def chunk_pages(
    pages: List[dict],
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> List[dict]:
    """Split fetched pages into overlapping chunks for retrieval."""
    chunks: List[dict] = []
    for page in pages:
        content = page.get("content", "")
        if not content.strip():
            continue
        for text in _split_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunks.append(
                {
                    "url": page.get("url", ""),
                    "title": page.get("title", ""),
                    "content": text,
                }
            )
    return chunks


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )
        return splitter.split_text(text)
    except ImportError:
        chunks: List[str] = []
        step = max(1, chunk_size - chunk_overlap)
        for start in range(0, len(text), step):
            chunk = text[start : start + chunk_size].strip()
            if chunk:
                chunks.append(chunk)
        return chunks
