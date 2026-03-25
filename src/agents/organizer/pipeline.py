"""Organizer Agent pipeline orchestration."""

import asyncio
from typing import Any, Callable, Optional

from loguru import logger

from src.agents.organizer.chunker import chunk_markdown
from src.agents.organizer.embedder import Embedder
from src.agents.organizer.image_extractor import ImageExtractor
from src.agents.organizer.note_classifier import NoteClassifier
from src.agents.organizer.note_formatter import NoteFormatter
from src.core.config import AppConfig
from src.core.events import (
    SSEEvent,
    error_event,
    progress_event,
    result_event,
    status_event,
)
from src.llm.client import LLMClient
from src.models.note import OrganizeResult
from src.storage.file_manager import FileManager
from src.storage.vector_store import VectorStore


class OrganizerPipeline:
    """Orchestrates the full note organization pipeline.

    Pipeline steps:
    1. Image semantic extraction (qwen3-vl-flash)
    2. Note formatting (qwen3.5-flash)
    3. Note classification (qwen3.5-plus)
    4. File storage (FileManager)
    5. Chunking + embedding (text-embedding-v4 → Qdrant)
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
        self._file_manager = file_manager
        self._vector_store = vector_store

        # Initialize sub-components
        self._image_extractor = ImageExtractor(
            llm_client=llm_client,
            model_config=config.get_model_config("image_semantic"),
        )
        self._note_formatter = NoteFormatter(
            llm_client=llm_client,
            model_config=config.get_model_config("note_organizer"),
        )
        self._note_classifier = NoteClassifier(
            llm_client=llm_client,
            model_config=config.get_model_config("note_classifier"),
            categories_path=str(config.categories_path),
        )

        embed_config = config.get_model_config("embedding")
        self._embedder = Embedder(
            llm_client=llm_client,
            vector_store=vector_store,
            dimension=embed_config.dimension or 1024,
            batch_size=embed_config.batch_size or 10,
        )

    async def run(
        self,
        raw_markdown: str,
        images_dir: Optional[str] = None,
        event_callback: Optional[Callable[[SSEEvent], Any]] = None,
    ) -> OrganizeResult:
        """Run the full organization pipeline.

        Args:
            raw_markdown: Raw Markdown content of the note.
            images_dir: Directory containing referenced images.
            event_callback: Async callback for SSE events.

        Returns:
            OrganizeResult with success status and file path.
        """
        self._llm.usage_tracker.reset_task_summary()

        async def emit(event: SSEEvent):
            if event_callback:
                await event_callback(event)

        try:
            # Step 1: Image semantic extraction
            await emit(progress_event("image_semantic", 0.05, "正在提取图像语义..."))
            # Default images_dir to notes root (images use paths relative to vault root)
            effective_images_dir = images_dir or self._config.note_storage.root_path
            content = await self._image_extractor.extract(
                markdown_content=raw_markdown,
                images_dir=effective_images_dir,
            )
            await emit(progress_event("image_semantic", 0.20, "图像语义提取完成"))

            # Step 2: Note formatting
            await emit(progress_event("note_format", 0.25, "正在整理笔记内容..."))
            content = await self._note_formatter.format(content)
            await emit(progress_event("note_format", 0.50, "笔记整理完成"))

            # Step 3: Classification
            await emit(progress_event("note_classify", 0.55, "正在分析笔记分类..."))
            classification = await self._note_classifier.classify(content)
            await emit(progress_event("note_classify", 0.65, f"分类: {classification.category}/{classification.subcategory}"))

            # Step 4: Save file
            await emit(progress_event("file_save", 0.70, "正在保存笔记文件..."))
            note_path = await self._file_manager.safe_write(
                category=classification.category,
                subcategory=classification.subcategory,
                filename=classification.title,
                content=content,
            )
            await emit(progress_event("file_save", 0.75, f"已保存至: {note_path}"))

            # Step 5: Chunk + Embed
            await emit(progress_event("embedding", 0.80, "正在生成向量嵌入..."))
            chunks = chunk_markdown(
                content,
                max_chunk_tokens=self._config.chunking.max_chunk_tokens,
                overlap_tokens=self._config.chunking.overlap_tokens,
            )
            chunk_count = await self._embedder.embed_and_store(
                note_path=note_path,
                note_title=classification.title,
                chunks=chunks,
            )
            await emit(progress_event("embedding", 0.95, f"已存储 {chunk_count} 个向量"))

            # Final result
            token_summary = self._llm.usage_tracker.get_task_summary()
            result = OrganizeResult(
                success=True,
                note_path=note_path,
                classification=classification,
                token_summary=token_summary,
            )

            await emit(result_event({
                "success": True,
                "note_path": note_path,
                "category": classification.category,
                "subcategory": classification.subcategory,
                "title": classification.title,
                "chunks": chunk_count,
                "token_summary": token_summary,
            }))

            logger.info(f"Organization complete: {note_path} ({chunk_count} chunks)")
            return result

        except Exception as e:
            logger.error(f"Organization pipeline failed: {e}")
            await emit(error_event(str(e), retry=False, step="pipeline"))

            return OrganizeResult(
                success=False,
                error=str(e),
                token_summary=self._llm.usage_tracker.get_task_summary(),
            )
