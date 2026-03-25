"""Hybrid retrieval combining dense and sparse vector search."""

from typing import Optional

from loguru import logger

from src.agents.querier.rewriter import RewriteResult
from src.llm.client import LLMClient
from src.storage.vector_store import SearchResult, VectorStore


class HybridRetriever:
    """Performs hybrid dense+sparse retrieval from Qdrant."""

    def __init__(
        self,
        llm_client: LLMClient,
        vector_store: VectorStore,
        dimension: int = 1024,
    ):
        self._llm = llm_client
        self._store = vector_store
        self._dimension = dimension

    async def retrieve(
        self,
        rewrite_result: RewriteResult,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Retrieve relevant note chunks using hybrid search.

        Args:
            rewrite_result: Rewritten query from QueryRewriter.
            top_k: Maximum number of results.

        Returns:
            List of SearchResult sorted by relevance.
        """
        query_text = rewrite_result.rewritten_query

        # Generate query embedding with text_type="query"
        embed_result = await self._llm.embed_with_retry(
            texts=[query_text],
            text_type="query",
            output_type="dense&sparse",
            dimension=self._dimension,
            step="query_embedding",
            instruct="Given a user's note search query, retrieve relevant personal notes",
        )

        if not embed_result.embeddings:
            logger.error("Failed to generate query embedding")
            return []

        emb_data = embed_result.embeddings[0]
        dense_vector = emb_data.get("embedding", [])

        # Extract sparse vector if available
        sparse_vector = None
        sparse_data = emb_data.get("sparse_embedding", None)
        if sparse_data:
            sparse_vector = {
                "indices": sparse_data.get("indices", []),
                "values": sparse_data.get("values", []),
            }

        # Hybrid search in Qdrant
        results = await self._store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            limit=top_k,
        )

        logger.info(f"Retrieved {len(results)} results for query: '{query_text[:50]}...'")
        return results
