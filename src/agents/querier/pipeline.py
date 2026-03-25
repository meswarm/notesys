"""Query Agent pipeline orchestration."""

from typing import Any, Callable, Optional

from loguru import logger

from src.agents.querier.retriever import HybridRetriever
from src.agents.querier.rewriter import QueryRewriter
from src.agents.querier.synthesizer import AnswerSynthesizer
from src.core.config import AppConfig
from src.core.events import (
    SSEEvent,
    error_event,
    progress_event,
    result_event,
    status_event,
)
from src.llm.client import LLMClient
from src.models.note import QueryResult
from src.storage.file_manager import FileManager
from src.storage.vector_store import VectorStore


class QuerierPipeline:
    """Orchestrates the full note query pipeline.

    Pipeline steps:
    1. Query rewriting (qwen3.5-flash)
    2. Hybrid retrieval (text-embedding-v4 → Qdrant)
    3. Answer synthesis (qwen3.5-plus)
    """

    def __init__(
        self,
        config: AppConfig,
        llm_client: LLMClient,
        file_manager: FileManager,
        vector_store: VectorStore,
    ):
        self._config = config
        self._llm = llm_client

        embed_config = config.get_model_config("embedding")

        self._rewriter = QueryRewriter(
            llm_client=llm_client,
            model_config=config.get_model_config("query_rewriter"),
        )
        self._retriever = HybridRetriever(
            llm_client=llm_client,
            vector_store=vector_store,
            dimension=embed_config.dimension or 1024,
        )
        self._synthesizer = AnswerSynthesizer(
            llm_client=llm_client,
            model_config=config.get_model_config("query_synthesizer"),
            file_manager=file_manager,
        )

    async def run(
        self,
        user_query: str,
        top_k: int = 10,
        event_callback: Optional[Callable[[SSEEvent], Any]] = None,
    ) -> QueryResult:
        """Run the full query pipeline.

        Args:
            user_query: User's query string.
            top_k: Maximum number of retrieval results.
            event_callback: Async callback for SSE events.

        Returns:
            QueryResult with answer and related notes.
        """
        self._llm.usage_tracker.reset_task_summary()

        async def emit(event: SSEEvent):
            if event_callback:
                await event_callback(event)

        try:
            # Step 1: Query rewriting
            await emit(progress_event("query_rewrite", 0.10, "正在优化查询..."))
            rewrite_result = await self._rewriter.rewrite(user_query)
            await emit(progress_event("query_rewrite", 0.20,
                                       f"查询改写: {rewrite_result.rewritten_query[:50]}..."))

            # Step 2: Hybrid retrieval
            await emit(progress_event("retrieval", 0.25, "正在检索相关笔记..."))
            search_results = await self._retriever.retrieve(rewrite_result, top_k=top_k)
            await emit(progress_event("retrieval", 0.50,
                                       f"检索到 {len(search_results)} 条相关内容"))

            if not search_results:
                await emit(result_event({
                    "success": True,
                    "answer": "未找到相关笔记。请尝试使用不同的关键词搜索。",
                    "related_notes": [],
                    "token_summary": self._llm.usage_tracker.get_task_summary(),
                }))
                return QueryResult(
                    success=True,
                    answer="未找到相关笔记。请尝试使用不同的关键词搜索。",
                    token_summary=self._llm.usage_tracker.get_task_summary(),
                )

            # Step 3: Answer synthesis
            await emit(progress_event("synthesis", 0.55, "正在整理回答..."))
            answer, related_notes = await self._synthesizer.synthesize(
                user_query=user_query,
                retrieval_results=search_results,
            )
            await emit(progress_event("synthesis", 0.90, "回答整理完成"))

            # Final result
            token_summary = self._llm.usage_tracker.get_task_summary()
            result = QueryResult(
                success=True,
                answer=answer,
                related_notes=related_notes,
                token_summary=token_summary,
            )

            await emit(result_event({
                "success": True,
                "answer": answer,
                "related_notes": related_notes,
                "token_summary": token_summary,
            }))

            logger.info(f"Query complete: {len(related_notes)} notes, {len(answer)} chars")
            return result

        except Exception as e:
            logger.error(f"Query pipeline failed: {e}")
            await emit(error_event(str(e), retry=False, step="pipeline"))

            return QueryResult(
                success=False,
                error=str(e),
                token_summary=self._llm.usage_tracker.get_task_summary(),
            )
