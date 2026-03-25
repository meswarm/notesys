"""Embedding generator and Qdrant storage."""

from typing import Any

from loguru import logger

from src.llm.client import LLMClient
from src.models.note import NoteChunk
from src.storage.vector_store import VectorStore


class Embedder:
    """Generates embeddings and stores them in Qdrant."""

    def __init__(
        self,
        llm_client: LLMClient,
        vector_store: VectorStore,
        dimension: int = 1024,
        batch_size: int = 10,
    ):
        self._llm = llm_client
        self._store = vector_store
        self._dimension = dimension
        self._batch_size = batch_size

    async def embed_and_store(
        self,
        note_path: str,
        note_title: str,
        chunks: list[NoteChunk],
    ) -> int:
        """Generate embeddings for chunks and store in Qdrant.

        First deletes any existing vectors for the note, then inserts new ones.

        Args:
            note_path: Relative path of the note file.
            note_title: Title of the note.
            chunks: List of text chunks to embed.

        Returns:
            Number of chunks stored.
        """
        if not chunks:
            return 0

        # Delete old vectors for this note
        await self._store.delete_by_note_path(note_path)

        # Process in batches of batch_size
        all_chunk_data = []

        for batch_start in range(0, len(chunks), self._batch_size):
            batch = chunks[batch_start:batch_start + self._batch_size]
            texts = [chunk.text for chunk in batch]

            # Call embedding API with dense+sparse
            result = await self._llm.embed_with_retry(
                texts=texts,
                text_type="document",
                output_type="dense&sparse",
                dimension=self._dimension,
                step="embedding",
            )

            # Combine chunk metadata with embeddings
            for i, chunk in enumerate(batch):
                if i >= len(result.embeddings):
                    break

                emb_data = result.embeddings[i]

                chunk_dict: dict[str, Any] = {
                    "note_path": note_path,
                    "note_title": note_title,
                    "chunk_index": chunk.chunk_index,
                    "heading": chunk.heading,
                    "chunk_text": chunk.text,
                    "dense_vector": emb_data.get("embedding", []),
                }

                # Add sparse vector if available
                sparse = emb_data.get("sparse_embedding", None)
                if sparse:
                    chunk_dict["sparse_vector"] = {
                        "indices": sparse.get("indices", []),
                        "values": sparse.get("values", []),
                    }

                all_chunk_data.append(chunk_dict)

        # Upsert all chunks to Qdrant
        count = await self._store.upsert_chunks(all_chunk_data)
        logger.info(f"Stored {count} chunks for note: {note_path}")
        return count
