"""Query Agent pipeline orchestration."""

from typing import Any, Callable, Optional

from loguru import logger

from src.agents.querier.retriever import HybridRetriever
from src.agents.querier.rewriter import QueryRewriter, RewriteResult
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
    1. Query rewriting (optional, controlled by enable_rewrite)
    2. Hybrid retrieval (text-embedding-v4 → Qdrant, always enabled)
    3. Answer synthesis (optional, controlled by enable_synthesis)
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
        enable_rewrite: Optional[bool] = None,
        enable_synthesis: Optional[bool] = None,
        event_callback: Optional[Callable[[SSEEvent], Any]] = None,
    ) -> QueryResult:
        """Run the query pipeline.

        Args:
            user_query: User's query string.
            top_k: Maximum number of retrieval results.
            enable_rewrite: Override config to enable/disable query rewriting.
                None = use config default.
            enable_synthesis: Override config to enable/disable answer synthesis.
                None = use config default.
            event_callback: Async callback for SSE events.

        Returns:
            QueryResult with answer and related notes.
        """
        self._llm.usage_tracker.reset_task_summary()

        # Resolve feature toggles: API param > config default
        do_rewrite = enable_rewrite if enable_rewrite is not None else self._config.query.enable_rewrite
        do_synthesis = enable_synthesis if enable_synthesis is not None else self._config.query.enable_synthesis

        async def emit(event: SSEEvent):
            if event_callback:
                await event_callback(event)

        try:
            # Step 1: Query rewriting (optional)
            if do_rewrite:
                await emit(progress_event("query_rewrite", 0.10, "正在优化查询..."))
                rewrite_result = await self._rewriter.rewrite(user_query)
                await emit(progress_event("query_rewrite", 0.20,
                                           f"查询改写: {rewrite_result.rewritten_query[:50]}..."))
            else:
                logger.info("Query rewrite disabled, using original query")
                rewrite_result = RewriteResult(rewritten_query=user_query)
                await emit(progress_event("query_rewrite", 0.20, "跳过查询改写"))

            # Step 2: Hybrid retrieval (always enabled)
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

            # Step 3: Answer synthesis (optional)
            if do_synthesis:
                await emit(progress_event("synthesis", 0.55, "正在整理回答..."))
                answer, related_notes = await self._synthesizer.synthesize(
                    user_query=user_query,
                    retrieval_results=search_results,
                )
                await emit(progress_event("synthesis", 0.90, "回答整理完成"))
            else:
                logger.info("Answer synthesis disabled, returning top document paths")
                # De-duplicate by note_path, keep best score, return top 5
                seen_paths: dict[str, Any] = {}
                for r in search_results:
                    if r.note_path not in seen_paths or r.score > seen_paths[r.note_path].score:
                        seen_paths[r.note_path] = r
                top_notes = sorted(seen_paths.values(), key=lambda r: r.score, reverse=True)[:5]

                related_notes = []
                answer_lines = []
                for note in top_notes:
                    score_pct = min(100, max(0, int(note.score * 100)))
                    related_notes.append({
                        "note_path": note.note_path,
                        "note_title": note.note_title,
                        "score": score_pct,
                    })
                    answer_lines.append(f"[{note.note_title}]({note.note_path}) — 相关度: {score_pct}%")

                answer = "\n".join(answer_lines)
                await emit(progress_event("synthesis", 0.90, "跳过结果综合，直接返回文档列表"))

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
