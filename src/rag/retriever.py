"""RAG retriever for context engineering.

Priority chain:
  1. FAISS + OpenAI text-embedding-3-small  (when OPENAI_API_KEY is set)
  2. BM25 keyword retrieval via rank_bm25   (no API key required)
  3. Truncation fallback                    (first k chunks)

When to use RAG vs. full context:
  - RAG wins when fetched content > ~40k tokens — it prevents context-window
    overflow and focuses the LLM on the most relevant evidence.
  - Full context wins for small tasks (< 30k tokens) — RAG adds embedding
    latency and can miss holistic cross-document connections.
"""

from __future__ import annotations

import os
from typing import List

from src.rag.chunker import chunk_pages


async def retrieve_relevant_chunks(
    pages: List[dict],
    query: str,
    k: int = 10,
) -> List[dict]:
    """Return the k most relevant text chunks from pages for query."""
    chunks = chunk_pages(pages)
    if not chunks:
        return pages

    if os.getenv("OPENAI_API_KEY"):
        try:
            return _faiss_retrieve(chunks, query, k)
        except Exception:
            pass

    return _bm25_retrieve(chunks, query, k)


def _faiss_retrieve(chunks: List[dict], query: str, k: int) -> List[dict]:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_openai import OpenAIEmbeddings

    docs = [
        Document(
            page_content=c["content"],
            metadata={"url": c["url"], "title": c["title"]},
        )
        for c in chunks
    ]
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vectorstore = FAISS.from_documents(docs, embeddings)
    results = vectorstore.similarity_search(query, k=k)
    return [
        {
            "url": d.metadata["url"],
            "title": d.metadata["title"],
            "content": d.page_content,
        }
        for d in results
    ]


def _bm25_retrieve(chunks: List[dict], query: str, k: int) -> List[dict]:
    try:
        from rank_bm25 import BM25Okapi

        corpus = [c["content"].lower().split() for c in chunks]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query.lower().split())
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [chunks[i] for i in top_indices]
    except ImportError:
        return chunks[:k]
