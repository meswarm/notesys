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

    Pipeline steps (each independently toggleable):
    1. Image semantic extraction (qwen3-vl-flash)
    2. Note formatting (qwen3.5-flash)
    3. Note classification + file storage (qwen3.5-plus + FileManager)
    4. Chunking + embedding (text-embedding-v4 → Qdrant)
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
        enable_image_semantic: Optional[bool] = None,
        enable_note_format: Optional[bool] = None,
        enable_classify_and_save: Optional[bool] = None,
        enable_embedding: Optional[bool] = None,
        event_callback: Optional[Callable[[SSEEvent], Any]] = None,
    ) -> OrganizeResult:
        """Run the organization pipeline.

        Args:
            raw_markdown: Raw Markdown content of the note.
            images_dir: Directory containing referenced images.
            enable_image_semantic: Override config for image semantic extraction.
                None = use config default.
            enable_note_format: Override config for note formatting.
                None = use config default.
            enable_classify_and_save: Override config for classification + file save.
                None = use config default.
            enable_embedding: Override config for chunking + embedding.
                None = use config default.
            event_callback: Async callback for SSE events.

        Returns:
            OrganizeResult with success status and file path.
        """
        self._llm.usage_tracker.reset_task_summary()

        # Resolve feature toggles: API param > config default
        org_cfg = self._config.organize
        do_image = enable_image_semantic if enable_image_semantic is not None else org_cfg.enable_image_semantic
        do_format = enable_note_format if enable_note_format is not None else org_cfg.enable_note_format
        do_classify = enable_classify_and_save if enable_classify_and_save is not None else org_cfg.enable_classify_and_save
        do_embed = enable_embedding if enable_embedding is not None else org_cfg.enable_embedding

        async def emit(event: SSEEvent):
            if event_callback:
                await event_callback(event)

        try:
            content = raw_markdown

            # Step 1: Image semantic extraction (optional)
            if do_image:
                await emit(progress_event("image_semantic", 0.05, "正在提取图像语义..."))
                effective_images_dir = images_dir or self._config.note_storage.root_path
                content = await self._image_extractor.extract(
                    markdown_content=content,
                    images_dir=effective_images_dir,
                )
                await emit(progress_event("image_semantic", 0.20, "图像语义提取完成"))
            else:
                logger.info("Image semantic extraction disabled, skipping")
                await emit(progress_event("image_semantic", 0.20, "跳过图像语义提取"))

            # Step 2: Note formatting (optional)
            if do_format:
                await emit(progress_event("note_format", 0.25, "正在整理笔记内容..."))
                content = await self._note_formatter.format(content)
                await emit(progress_event("note_format", 0.50, "笔记整理完成"))
            else:
                logger.info("Note formatting disabled, skipping")
                await emit(progress_event("note_format", 0.50, "跳过笔记整理"))

            # Step 3: Classification + Save (optional)
            classification = None
            note_path = ""
            if do_classify:
                await emit(progress_event("note_classify", 0.55, "正在分析笔记分类..."))
                classification = await self._note_classifier.classify(content)
                await emit(progress_event("note_classify", 0.65, f"分类: {classification.category}/{classification.subcategory}"))

                # Add date stamp at the top before saving
                from datetime import datetime
                date_str = datetime.now().strftime("%Y年%m月%d日")
                content = f"{date_str}\n\n{content}"

                await emit(progress_event("file_save", 0.70, "正在保存笔记文件..."))
                note_path = await self._file_manager.safe_write(
                    category=classification.category,
                    subcategory=classification.subcategory,
                    filename=classification.title,
                    content=content,
                )
                await emit(progress_event("file_save", 0.75, f"已保存至: {note_path}"))
            else:
                logger.info("Classification and save disabled, skipping")
                await emit(progress_event("note_classify", 0.75, "跳过分类与存储"))

            # Step 4: Chunk + Embed (optional, requires note_path from step 3)
            chunk_count = 0
            if do_embed:
                if not note_path:
                    logger.warning("Embedding enabled but no note_path (classify_and_save was disabled), skipping embedding")
                    await emit(progress_event("embedding", 0.95, "跳过嵌入（无存储路径）"))
                else:
                    await emit(progress_event("embedding", 0.80, "正在生成向量嵌入..."))
                    chunks = chunk_markdown(
                        content,
                        max_chunk_tokens=self._config.chunking.max_chunk_tokens,
                        overlap_tokens=self._config.chunking.overlap_tokens,
                    )
                    chunk_count = await self._embedder.embed_and_store(
                        note_path=note_path,
                        note_title=classification.title if classification else "untitled",
                        chunks=chunks,
                    )
                    await emit(progress_event("embedding", 0.95, f"已存储 {chunk_count} 个向量"))
            else:
                logger.info("Embedding disabled, skipping")
                await emit(progress_event("embedding", 0.95, "跳过向量嵌入"))

            # Final result
            token_summary = self._llm.usage_tracker.get_task_summary()
            result = OrganizeResult(
                success=True,
                note_path=note_path,
                classification=classification,
                token_summary=token_summary,
            )

            result_data = {
                "success": True,
                "note_path": note_path,
                "category": classification.category if classification else "",
                "subcategory": classification.subcategory if classification else "",
                "title": classification.title if classification else "",
                "chunks": chunk_count,
                "token_summary": token_summary,
            }

            # Include processed content when classify_and_save is disabled
            if not do_classify:
                result_data["processed_content"] = content

            await emit(result_event(result_data))

            logger.info(f"Organization complete: {note_path or '(not saved)'} ({chunk_count} chunks)")
            return result

        except Exception as e:
            logger.error(f"Organization pipeline failed: {e}")
            await emit(error_event(str(e), retry=False, step="pipeline"))

            return OrganizeResult(
                success=False,
                error=str(e),
                token_summary=self._llm.usage_tracker.get_task_summary(),
            )
