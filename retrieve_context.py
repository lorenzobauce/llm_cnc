# retrieve_context.py
"""RAG helper: index `CAM.txt` and fetch the most relevant chunks.

Usage:
    from retrieve_context import get_relevant_context
    context_chunks = get_relevant_context("milling pocket aluminium", k=3)
"""
import os
import shutil
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
_DOC_PATH = Path("CAM.txt")                  # technical formulary
_INDEX_DIR = Path("vectorstore")             # persistent FAISS folder
_CHUNK_SIZE = 1000                           # characters per chunk
_CHUNK_OVERLAP = 100                         # overlap for better context

# ---------------------------------------------------------------------------
# INITIALISE (load env, embeddings)
# ---------------------------------------------------------------------------
load_dotenv()
_embeddings = OpenAIEmbeddings()

# ---------------------------------------------------------------------------
# BUILD OR LOAD INDEX
# ---------------------------------------------------------------------------

def _build_index() -> FAISS:
    """Create FAISS index from `CAM.txt`. Saved for later reuse."""
    if not _DOC_PATH.exists():
        raise FileNotFoundError(f"Formulary file not found: {_DOC_PATH}")

    text = _DOC_PATH.read_text(encoding="utf-8")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    docs = splitter.create_documents([text])

    store = FAISS.from_documents(docs, _embeddings)
    store.save_local(_INDEX_DIR.as_posix())
    return store

_vectorstore = _build_index()

# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def get_relevant_context(query: str, k: int = 4) -> List[str]:
    """Return `k` most relevant chunks from the formulary for a given query."""
    docs = _vectorstore.similarity_search(query, k=k)
    return [d.page_content for d in docs]

if __name__ == "__main__":
    # quick CLI test
    q = input("Query for formulary context: ")
    res = get_relevant_context(q)
    print("\n--- Retrieved Chunks ---\n")
    for ch in res:
        print(ch)
        print("\n" + "-" * 40 + "\n")
