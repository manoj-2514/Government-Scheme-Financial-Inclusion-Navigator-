"""Knowledge base vector indexing and retrieval.

Chunks raw text documents from backend/data/scheme_docs/, generates
embeddings using SentenceTransformers all-MiniLM-L6-v2, and indexes/queries
them using FAISS.
"""

import os
import pickle
import sys
from pathlib import Path
from typing import Any, Dict, List

import faiss
import numpy as np

# Reconfigure stdout to use UTF-8 just in case we run this file directly on Windows
if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Module-level model singleton — loaded once at import, reused for all calls
# ---------------------------------------------------------------------------
_EMBED_MODEL: Any = None


def _get_embed_model() -> Any:
    """Return the shared SentenceTransformer instance, loading it on first call."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from sentence_transformers import SentenceTransformer
        _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBED_MODEL

# ---------------------------------------------------------------------------
# Directories and Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent            # backend/tools/
_BACKEND_DIR = _THIS_DIR.parent                        # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                    # project root

# Path 1: relative to active backend/
_DOCS_DIR_1 = _BACKEND_DIR / "data" / "scheme_docs"
# Path 2: relative to sibling git repo backend/
_DOCS_DIR_2 = (
    _PROJECT_ROOT
    / "Government-Scheme-Financial-Inclusion-Navigator-"
    / "backend"
    / "data"
    / "scheme_docs"
)

_INDEX_DIR = _BACKEND_DIR / "data" / "faiss_index"
_INDEX_PATH = _INDEX_DIR / "index.faiss"
_METADATA_PATH = _INDEX_DIR / "metadata.pkl"


def get_docs_dir() -> Path:
    """Find the directory containing the text files."""
    if _DOCS_DIR_1.exists() and any(_DOCS_DIR_1.glob("*.txt")):
        return _DOCS_DIR_1
    return _DOCS_DIR_2


# ── Ingestion and Chunking logic ──────────────────────────────────────────


def chunk_text(
    text: str, chunk_size: int = 400, overlap: int = 50
) -> List[str]:
    """Split text into chunks of roughly chunk_size words with overlap."""
    words = text.split()
    chunks = []

    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size

    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        chunk_content = " ".join(chunk_words).strip()
        if chunk_content:
            chunks.append(chunk_content)

        # Stop when we've read up to or past the end of the list
        if i + chunk_size >= len(words):
            break

    return chunks


def ingest_documents() -> int:
    """Read TXT files, chunk them, generate embeddings, and save FAISS index."""
    docs_dir = get_docs_dir()
    if not docs_dir.exists():
        raise FileNotFoundError(
            f"Documents directory not found at: {docs_dir.resolve()}"
        )

    print(f"Loading files from: {docs_dir.resolve()}")
    txt_files = list(docs_dir.glob("*.txt"))

    if not txt_files:
        print("No .txt documents found to index.")
        return 0

    # Use the shared sentence transformer model
    print("Loading SentenceTransformer model 'all-MiniLM-L6-v2'...")
    model = _get_embed_model()

    all_chunks = []
    all_metadata = []

    for txt_file in txt_files:
        filename = txt_file.name
        try:
            with open(txt_file, "r", encoding="utf-8") as f:
                text = f.read()

            chunks = chunk_text(text)
            print(f"  - {filename}: split into {len(chunks)} chunks.")

            for idx, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_metadata.append(
                    {
                        "source": filename,
                        "chunk_index": idx,
                        "text": chunk,
                    }
                )
        except Exception as e:
            print(f"  - Error reading {filename}: {e}")

    if not all_chunks:
        print("No text chunks extracted.")
        return 0

    print(f"Total chunks across all documents: {len(all_chunks)}")
    print("Generating vector embeddings (this might take a moment)...")
    embeddings = model.encode(all_chunks, show_progress_bar=True)
    embeddings = np.array(embeddings).astype("float32")

    # Build FAISS index
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    # Save to disk
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(_INDEX_PATH))

    with open(_METADATA_PATH, "wb") as f:
        pickle.dump(all_metadata, f)

    print(f"FAISS index and metadata successfully saved to {_INDEX_DIR.resolve()}")
    return len(all_chunks)


# ── Query and Retrieval logic ─────────────────────────────────────────────


def query_knowledge_base(question: str) -> str:
    """Retrieve top 3 most relevant chunks from the FAISS database."""
    if not _INDEX_PATH.exists() or not _METADATA_PATH.exists():
        return (
            "Knowledge base index is empty. "
            "Please run 'python knowledge_base.py' to ingest guidelines."
        )

    # Load vector index and metadata mapping
    index = faiss.read_index(str(_INDEX_PATH))
    with open(_METADATA_PATH, "rb") as f:
        metadata = pickle.load(f)

    # Safety check: index file exists but is actually empty (0 vectors) or
    # metadata is empty — this happens if ingestion ran against the WRONG
    # folder, or against an empty scheme_docs directory.
    if index.ntotal == 0 or not metadata:
        return (
            f"Knowledge base index exists at {_INDEX_PATH.resolve()} but "
            f"contains 0 indexed chunks. This usually means ingestion ran "
            f"against an empty or wrong scheme_docs folder. Please re-run "
            f"'python knowledge_base.py' from inside the correct backend/ "
            f"directory to rebuild it."
        )

    # Reuse the shared model singleton
    model = _get_embed_model()
    query_vector = model.encode([question]).astype("float32")

    # Search top 3 results
    k = min(3, len(metadata))
    distances, indices = index.search(query_vector, k)

    results = []
    for rank, idx in enumerate(indices[0]):
        if idx == -1 or idx >= len(metadata):
            continue

        item = metadata[idx]
        source = item["source"]
        chunk_idx = item["chunk_index"]
        text = item["text"]

        chunk_str = f"[Source: {source} (Chunk {chunk_idx})]\n{text}"
        results.append(chunk_str)

    if not results:
        return "No relevant guidelines found in the knowledge base."

    return "\n\n=== RELEVANT CONTEXT CHUNK ===\n".join(results)


# ── Self-running block for indexing and verification ──────────────────────

if __name__ == "__main__":
    print("=== STARTING KNOWLEDGE BASE INGESTION ===")
    try:
        count = ingest_documents()
        print(f"Ingestion finished. Total chunks indexed: {count}")

        print("\n=== RUNNING SAMPLE QUERY VERIFICATION ===")
        sample_q = "What is the eligibility for PM-KISAN?"
        print(f"Query: '{sample_q}'\n")
        context = query_knowledge_base(sample_q)
        print("Retrieved Context:")
        print(context)
    except Exception as exc:
        print(f"Execution failed: {exc}")