"""Organizer Agent pipeline orchestration."""

from datetime import datetime
from typing import Any, Callable, Optional

from loguru import logger

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


class OrganizerPipeline:
    """Orchestrates the note organization pipeline.

    Pipeline steps (each independently toggleable):
    1. Image semantic extraction (qwen3-vl-flash)
    2. Note formatting (qwen3.5-plus)
    3. Note classification + file storage (qwen3.5-flash + FileManager)

    notes_root_path is accepted per-request so different callers can use
    their own storage directories without reconfiguring the service.

    Note: Vector embedding is handled by the independent ragData service.
    """

    def __init__(
        self,
        config: AppConfig,
        llm_client: LLMClient,
    ):
        self._config = config
        self._llm = llm_client

        # Initialize sub-components (stateless wrt storage path)
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

    def _make_file_manager(self, notes_root_path: Optional[str]) -> FileManager:
        """Create a FileManager for the given root path.

        Falls back to the server-level NOTES_ROOT_PATH if not provided.
        """
        root = notes_root_path or self._config.note_storage.root_path
        return FileManager(root_path=root)

    async def run(
        self,
        raw_markdown: str,
        notes_root_path: Optional[str] = None,
        images_dir: Optional[str] = None,
        enable_image_semantic: Optional[bool] = None,
        enable_note_format: Optional[bool] = None,
        enable_classify_and_save: Optional[bool] = None,
        add_date_stamp: Optional[bool] = True,
        event_callback: Optional[Callable[[SSEEvent], Any]] = None,
    ) -> OrganizeResult:
        """Run the organization pipeline.

        Args:
            raw_markdown: Raw Markdown content of the note.
            notes_root_path: Root directory for storing notes. Overrides the
                server-level NOTES_ROOT_PATH for this request. Categories are
                derived by scanning the 1st/2nd level directories of this path.
            images_dir: Directory containing referenced images. Defaults to
                notes_root_path (or server default) if not provided.
            enable_image_semantic: Override config for image semantic extraction.
                None = use config default.
            enable_note_format: Override config for note formatting.
                None = use config default.
            enable_classify_and_save: Override config for classification + file save.
                None = use config default.
            add_date_stamp: Prepend a date stamp (YYYY-MM-DD) before saving.
                Default True.
            event_callback: Async callback for SSE events.

        Returns:
            OrganizeResult with success status and file path.
        """
        self._llm.usage_tracker.reset_task_summary()

        # Build a FileManager for this request's root path
        file_manager = self._make_file_manager(notes_root_path)
        effective_root = str(file_manager.root_path)

        # Resolve feature toggles: API param > config default
        org_cfg = self._config.organize
        do_image    = enable_image_semantic    if enable_image_semantic    is not None else org_cfg.enable_image_semantic
        do_format   = enable_note_format       if enable_note_format       is not None else org_cfg.enable_note_format
        do_classify = enable_classify_and_save if enable_classify_and_save is not None else org_cfg.enable_classify_and_save

        async def emit(event: SSEEvent):
            if event_callback:
                await event_callback(event)

        try:
            content = raw_markdown

            # Step 1: Image semantic extraction (optional)
            if do_image:
                await emit(progress_event("image_semantic", 0.05, "正在提取图像语义..."))
                # images_dir defaults to the same root as the notes themselves
                effective_images_dir = images_dir or effective_root
                content = await self._image_extractor.extract(
                    markdown_content=content,
                    images_dir=effective_images_dir,
                )
                await emit(progress_event("image_semantic", 0.25, "图像语义提取完成"))
            else:
                logger.info("Image semantic extraction disabled, skipping")
                await emit(progress_event("image_semantic", 0.25, "跳过图像语义提取"))

            # Step 2: Note formatting (optional)
            if do_format:
                await emit(progress_event("note_format", 0.30, "正在整理笔记内容..."))
                content = await self._note_formatter.format(content)
                await emit(progress_event("note_format", 0.60, "笔记整理完成"))
            else:
                logger.info("Note formatting disabled, skipping")
                await emit(progress_event("note_format", 0.60, "跳过笔记整理"))

            # Step 3: Classification + Save (optional)
            classification = None
            note_path = ""
            if do_classify:
                await emit(progress_event("note_classify", 0.65, "正在分析笔记分类..."))

                # Derive categories by scanning the actual directory structure
                scanned_categories = await file_manager.list_directories()
                if scanned_categories:
                    logger.info(
                        f"Using {sum(len(v) for v in scanned_categories.values())} "
                        f"subcategories scanned from {effective_root}"
                    )
                else:
                    logger.info("No categories found in directory, LLM will create new ones")

                classification = await self._note_classifier.classify(
                    content,
                    categories=scanned_categories or None,
                )
                await emit(progress_event("note_classify", 0.75, f"分类: {classification.category}/{classification.subcategory}"))

                # Prepend date stamp before saving
                if add_date_stamp:
                    date_str = datetime.now().strftime("%Y-%m-%d")
                    content = f"{date_str}\n\n{content}"

                await emit(progress_event("file_save", 0.80, "正在保存笔记文件..."))
                note_path = await file_manager.safe_write(
                    category=classification.category,
                    subcategory=classification.subcategory,
                    filename=classification.title,
                    content=content,
                )
                await emit(progress_event("file_save", 0.95, f"已保存至: {note_path}"))
            else:
                logger.info("Classification and save disabled, skipping")
                await emit(progress_event("note_classify", 0.95, "跳过分类与存储"))

            # Final result
            token_summary = self._llm.usage_tracker.get_task_summary()
            result = OrganizeResult(
                success=True,
                note_path=note_path,
                classification=classification,
                token_summary=token_summary,
            )

            result_data: dict = {
                "success": True,
                "note_path": note_path,
                "category": classification.category if classification else "",
                "subcategory": classification.subcategory if classification else "",
                "title": classification.title if classification else "",
                "token_summary": token_summary,
            }

            # Include processed content when classify_and_save is disabled
            if not do_classify:
                result_data["processed_content"] = content

            await emit(result_event(result_data))

            logger.info(f"Organization complete: {note_path or '(not saved)'}")
            return result

        except Exception as e:
            logger.error(f"Organization pipeline failed: {e}")
            await emit(error_event(str(e), retry=False, step="pipeline"))

            return OrganizeResult(
                success=False,
                error=str(e),
                token_summary=self._llm.usage_tracker.get_task_summary(),
            )
