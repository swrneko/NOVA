"""
RAG (Retrieval-Augmented Generation) adapter using ChromaDB.
Indexes documents and provides semantic search for the LLM context.
"""

import os
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass

import chromadb
from chromadb.config import Settings

from nova.config import (
    RAG_CHROMA_PATH,
    RAG_EMBEDDING_MODEL,
    RAG_TOP_K,
    RAG_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
    RAG_DOCUMENT_SOURCES,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result from the RAG system."""
    content: str
    source: str
    metadata: dict
    distance: float


def chunk_text(text: str, chunk_size: int = RAG_CHUNK_SIZE, overlap: int = RAG_CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # Try to break at a sentence or word boundary
        if end < len(text):
            for sep in (". ", "\n", " "):
                last_sep = chunk.rfind(sep)
                if last_sep > chunk_size // 2:
                    end = start + last_sep + len(sep)
                    chunk = text[start:end]
                    break
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


def _file_hash(path: str) -> str:
    """Compute a quick hash of a file for change detection."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return ""


class RAGAdapter:
    """
    Manages document indexing and retrieval using ChromaDB.

    Usage:
        rag = RAGAdapter()
        await rag.build_index()   # index all document sources
        results = rag.search("how to install packages in arch")
    """

    COLLECTION_NAME = "nova_documents"

    def __init__(self, collection_name: str = COLLECTION_NAME):
        self.collection_name = collection_name

        # Initialize ChromaDB with local persistent storage
        self._client = chromadb.PersistentClient(
            path=RAG_CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # Track indexed files for incremental updates
        self._indexed_files: dict[str, str] = {}  # path -> hash
        self._load_indexed_files()

    def _load_indexed_files(self):
        """Load the list of already indexed files from ChromaDB metadata."""
        if self._collection.count() > 0:
            results = self._collection.get(
                include=["metadatas"],
                limit=self._collection.count(),
            )
            if results.get("metadatas"):
                for meta in results["metadatas"]:
                    fpath = meta.get("source", "")
                    fhash = meta.get("file_hash", "")
                    if fpath and fhash:
                        self._indexed_files[fpath] = fhash

    async def build_index(self, sources: list[str] | None = None):
        """
        Build or update the index from document sources.

        Only indexes new or modified files (incremental update).

        Args:
            sources: List of directory paths to scan for documents.
                     Defaults to RAG_DOCUMENT_SOURCES from config.
        """
        if sources is None:
            sources = RAG_DOCUMENT_SOURCES

        supported_extensions = {".md", ".txt", ".rst", ".pdf"}
        total_indexed = 0
        total_new = 0

        for source_dir in sources:
            source_path = Path(source_dir)
            if not source_path.exists():
                logger.debug(f"Source directory not found: {source_dir}")
                continue

            for file_path in source_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix not in supported_extensions:
                    continue

                fpath_str = str(file_path)
                file_hash = _file_hash(fpath_str)

                # Skip if file hasn't changed
                if self._indexed_files.get(fpath_str) == file_hash:
                    logger.debug(f"Skipping unchanged file: {fpath_str}")
                    continue

                # Index the file
                try:
                    count = await self._index_file(fpath_str)
                    total_new += count
                    self._indexed_files[fpath_str] = file_hash
                except Exception as e:
                    logger.error(f"Failed to index {fpath_str}: {e}")

            total_indexed += 1

        logger.info(
            f"Index built: scanned {total_indexed} directories, "
            f"indexed {total_new} new/updated document chunks"
        )

    async def _index_file(self, file_path: str) -> int:
        """
        Index a single file into ChromaDB.

        Returns the number of chunks indexed.
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            text = self._read_pdf(file_path)
        else:
            text = self._read_text_file(file_path)

        if not text:
            return 0

        chunks = chunk_text(text)
        if not chunks:
            return 0

        # Generate IDs for each chunk
        ids = [
            f"{file_path}::chunk_{i}"
            for i in range(len(chunks))
        ]

        # Metadatas
        metadatas = [
            {
                "source": file_path,
                "file_hash": _file_hash(file_path),
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i in range(len(chunks))
        ]

        # Delete old chunks from this file (for re-indexing)
        old_ids = [
            doc_id for doc_id in ids
            if doc_id.startswith(f"{file_path}::")
        ]
        # Actually query existing to find what to delete
        existing = self._collection.get(
            where={"source": file_path},
            include=[],
        )
        if existing.get("ids"):
            self._collection.delete(ids=existing["ids"])

        # Add chunks to collection
        self._collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
        )

        logger.debug(f"Indexed {len(chunks)} chunks from {file_path}")
        return len(chunks)

    def _read_text_file(self, file_path: str) -> str:
        """Read a text file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return ""

    def _read_pdf(self, file_path: str) -> str:
        """Read a PDF file (requires pypdf)."""
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except ImportError:
            logger.warning("pypdf not installed, skipping PDF: " + file_path)
            return ""
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {e}")
            return ""

    def search(self, query: str, top_k: int = RAG_TOP_K) -> list[SearchResult]:
        """
        Search the index for relevant documents.

        Args:
            query: The user's question or search query
            top_k: Number of results to return

        Returns:
            List of SearchResult objects
        """
        if self._collection.count() == 0:
            logger.warning("RAG index is empty. Build it with build_index() first.")
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error(f"RAG search error: {e}")
            return []

        search_results = []
        if results.get("documents"):
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                search_results.append(
                    SearchResult(
                        content=doc,
                        source=meta.get("source", "unknown"),
                        metadata=meta,
                        distance=dist,
                    )
                )

        logger.debug(
            f"RAG search for '{query[:50]}...' returned {len(search_results)} results"
        )
        return search_results

    def format_context(self, query: str, top_k: int = RAG_TOP_K) -> str:
        """
        Search and format results as a context string for the LLM.

        Returns a formatted string that can be injected into the LLM prompt.
        """
        results = self.search(query, top_k=top_k)
        if not results:
            return ""

        context_parts = []
        for i, result in enumerate(results, 1):
            source_name = Path(result.source).name
            context_parts.append(
                f"[Источник {i}: {source_name}]\n{result.content}"
            )

        return "\n\n---\n\n".join(context_parts)

    def get_stats(self) -> dict:
        """Return statistics about the index."""
        return {
            "total_documents": self._collection.count(),
            "indexed_files": len(self._indexed_files),
            "chroma_path": RAG_CHROMA_PATH,
        }

    def clear_index(self):
        """Delete the entire index."""
        self._client.delete_collection(self.collection_name)
        self._indexed_files.clear()
        logger.info("RAG index cleared")
