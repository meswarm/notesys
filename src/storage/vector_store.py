"""Qdrant vector store wrapper with hybrid dense+sparse search support."""

import uuid
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    Fusion,
    FusionQuery,
    MatchValue,
    PointStruct,
    Prefetch,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)


class SearchResult(BaseModel):
    """Single search result from Qdrant."""

    score: float
    note_path: str
    note_title: str
    chunk_index: int
    heading: str
    chunk_text: str


class VectorStore:
    """Qdrant vector store with hybrid dense+sparse search.

    Manages a single collection with both dense vectors (for semantic search)
    and sparse vectors (for keyword/BM25-equivalent search), using Reciprocal
    Rank Fusion (RRF) for result merging.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        grpc_port: int = 6334,
        collection_name: str = "notes",
        dense_dim: int = 1024,
    ):
        """Initialize Qdrant client and connection.

        Args:
            host: Qdrant server host.
            port: Qdrant REST API port.
            grpc_port: Qdrant gRPC port.
            collection_name: Name of the collection.
            dense_dim: Dimension of dense vectors.
        """
        self._client = QdrantClient(host=host, port=port, grpc_port=grpc_port)
        self._collection = collection_name
        self._dense_dim = dense_dim

    async def init_collection(self) -> None:
        """Create collection if it doesn't exist.

        Configures both dense and sparse vector indices.
        """
        import asyncio

        def _sync_init():
            collections = self._client.get_collections().collections
            existing_names = [c.name for c in collections]

            if self._collection in existing_names:
                logger.info(f"Collection '{self._collection}' already exists")
                return

            self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "dense": VectorParams(
                        size=self._dense_dim,
                        distance=Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(
                        index=SparseIndexParams(on_disk=False),
                    )
                },
            )
            logger.info(f"Created collection '{self._collection}' with dense({self._dense_dim}d) + sparse vectors")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_init)

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
    ) -> int:
        """Batch upsert note chunks with dense and sparse vectors.

        Args:
            chunks: List of chunk dicts, each containing:
                - note_path: str
                - note_title: str
                - chunk_index: int
                - heading: str
                - chunk_text: str
                - dense_vector: list[float]
                - sparse_vector: dict with 'indices' and 'values'

        Returns:
            Number of points upserted.
        """
        import asyncio

        points = []
        for chunk in chunks:
            point_id = str(uuid.uuid4())

            vectors = {
                "dense": chunk["dense_vector"],
            }

            # Add sparse vector if available
            if "sparse_vector" in chunk and chunk["sparse_vector"]:
                sparse_data = chunk["sparse_vector"]
                vectors["sparse"] = SparseVector(
                    indices=sparse_data["indices"],
                    values=sparse_data["values"],
                )

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vectors,
                    payload={
                        "note_path": chunk["note_path"],
                        "note_title": chunk["note_title"],
                        "chunk_index": chunk["chunk_index"],
                        "heading": chunk["heading"],
                        "chunk_text": chunk["chunk_text"],
                    },
                )
            )

        def _sync_upsert():
            self._client.upsert(
                collection_name=self._collection,
                points=points,
            )
            return len(points)

        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(None, _sync_upsert)
        logger.info(f"Upserted {count} chunks to collection '{self._collection}'")
        return count

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: Optional[dict] = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Perform hybrid dense+sparse search with RRF fusion.

        Args:
            dense_vector: Dense query vector.
            sparse_vector: Optional sparse query vector (dict with 'indices' and 'values').
            limit: Maximum number of results.

        Returns:
            List of SearchResult sorted by relevance.
        """
        import asyncio

        def _sync_search():
            if sparse_vector and sparse_vector.get("indices"):
                # Hybrid search with RRF fusion
                results = self._client.query_points(
                    collection_name=self._collection,
                    prefetch=[
                        Prefetch(
                            query=dense_vector,
                            using="dense",
                            limit=limit * 2,
                        ),
                        Prefetch(
                            query=SparseVector(
                                indices=sparse_vector["indices"],
                                values=sparse_vector["values"],
                            ),
                            using="sparse",
                            limit=limit * 2,
                        ),
                    ],
                    query=FusionQuery(fusion=Fusion.RRF),
                    limit=limit,
                )
            else:
                # Dense-only search
                results = self._client.query_points(
                    collection_name=self._collection,
                    query=dense_vector,
                    using="dense",
                    limit=limit,
                )

            return results

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _sync_search)

        search_results = []
        for point in results.points:
            payload = point.payload or {}
            search_results.append(
                SearchResult(
                    score=point.score if point.score is not None else 0.0,
                    note_path=payload.get("note_path", ""),
                    note_title=payload.get("note_title", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    heading=payload.get("heading", ""),
                    chunk_text=payload.get("chunk_text", ""),
                )
            )

        return search_results

    async def delete_by_note_path(self, note_path: str) -> int:
        """Delete all chunks belonging to a specific note.

        Used when re-organizing a note to clear old vectors before inserting new ones.

        Args:
            note_path: Relative path of the note.

        Returns:
            Number of points deleted.
        """
        import asyncio

        def _sync_delete():
            # Count points before deletion
            count_result = self._client.count(
                collection_name=self._collection,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="note_path",
                            match=MatchValue(value=note_path),
                        )
                    ]
                ),
            )
            count = count_result.count

            if count > 0:
                self._client.delete(
                    collection_name=self._collection,
                    points_selector=FilterSelector(
                        filter=Filter(
                            must=[
                                FieldCondition(
                                    key="note_path",
                                    match=MatchValue(value=note_path),
                                )
                            ]
                        )
                    ),
                )
                logger.info(f"Deleted {count} chunks for note: {note_path}")

            return count

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_delete)
