"""
RAG search over workshop materials using ChromaDB.

Exposes search_materials(query) — called by quiz_core.py via dynamic import.
"""

from pathlib import Path

CHROMA_PATH = Path.home() / ".workshop-rag" / "chroma"
COLLECTION_NAME = "workshop_materials"
EMBED_MODEL = "all-mpnet-base-v2"
TOP_K = 5

_embedder = None
_collection = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_collection():
    global _collection
    if _collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def search_materials(query: str) -> list[dict]:
    """Return top-K chunks matching query. Gracefully returns fallback if index is empty."""
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return [{"content": "No materials indexed yet. Run the daemon first.", "source": "N/A", "page": "N/A"}]
        embedder = _get_embedder()
        query_embedding = embedder.encode(query).tolist()
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(TOP_K, collection.count()),
            include=["documents", "metadatas"],
        )
        chunks = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            chunks.append({
                "content": doc,
                "source": meta.get("source", "Unknown"),
                "page": str(meta.get("page", "N/A")),
            })
        return chunks
    except Exception as e:
        return [{"content": f"RAG search failed: {e}", "source": "Error", "page": "N/A"}]
