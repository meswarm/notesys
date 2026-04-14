"""Vector store sync service — keeps Qdrant in sync with notes on disk.

Runs as a background asyncio task during the application lifespan.
Periodically scans the notes root directory, detects file changes,
and updates the vector store accordingly.
"""

import asyncio
from typing import Optional

from loguru import logger

from src.agents.organizer.chunker import chunk_markdown
from src.agents.organizer.embedder import Embedder
from src.core.config import AppConfig
from src.storage.vector_store import VectorStore
from src.sync.scanner import FileScanner


class SyncService:
    """Background service that synchronizes notes on disk with Qdrant vectors.

    Lifecycle:
        1. start() — launches the background sync loop
        2. The loop wakes every `interval_seconds`, scans for changes, and processes them
        3. stop() — cancels the background task gracefully

    Concurrency safety:
        - Uses an asyncio.Lock so the sync loop and manual triggers don't overlap
        - The organize pipeline should call `notify_skip(path)` to prevent
          double-processing of files that were just organized
    """

    def __init__(
        self,
        config: AppConfig,
        vector_store: VectorStore,
        embedder: Embedder,
    ):
        self._config = config
        self._vector_store = vector_store
        self._embedder = embedder
        self._scanner = FileScanner(config.note_storage.root_path, min_depth=config.sync.min_depth)

        self._interval = config.sync.interval_seconds
        self._batch_limit = config.sync.batch_limit
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._running = False

        # Paths currently being processed by the organize pipeline.
        # The sync service will skip these to avoid conflicts.
        self._skip_paths: set[str] = set()

    def notify_skip(self, note_path: str) -> None:
        """Mark a path as being processed by the organize pipeline.

        The sync service will skip this path in its current/next cycle.

        Args:
            note_path: Relative path of the note being organized.
        """
        self._skip_paths.add(note_path)

    def notify_done(self, note_path: str) -> None:
        """Mark a path as done being processed by the organize pipeline.

        Also updates the scanner's fingerprint cache so the next sync
        cycle won't treat this file as modified.

        Args:
            note_path: Relative path of the note that was organized.
        """
        self._skip_paths.discard(note_path)
        self._scanner.mark_synced(note_path)

    def start(self) -> None:
        """Start the background sync loop."""
        if self._task is not None:
            logger.warning("SyncService already started")
            return

        # Restore fingerprint cache from last run
        self._scanner.load_cache()

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="sync-service")
        logger.info(
            f"🔄 SyncService started (interval={self._interval}s, "
            f"batch_limit={self._batch_limit})"
        )

    async def stop(self) -> None:
        """Stop the background sync loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Persist fingerprint cache for next startup
        self._scanner.save_cache()

        logger.info("SyncService stopped")

    async def run_once(self) -> dict:
        """Run a single sync cycle (for manual trigger / API endpoint).

        Returns:
            Summary dict with counts of added, deleted, modified, and errors.
        """
        async with self._lock:
            return await self._sync_cycle()

    async def run_full_rebuild(self) -> dict:
        """Clear all vectors and rebuild from scratch.

        Returns:
            Summary dict with count of files processed and errors.
        """
        async with self._lock:
            return await self._full_rebuild()

    async def _loop(self) -> None:
        """Main background loop — runs sync cycle every N seconds."""
        # Wait a short time after startup before first sync
        await asyncio.sleep(5)

        while self._running:
            try:
                async with self._lock:
                    await self._sync_cycle()
            except Exception as e:
                logger.error(f"Sync cycle failed: {e}")

            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _sync_cycle(self) -> dict:
        """Execute one sync cycle: scan → diff → process changes.

        Returns:
            Summary dict.
        """
        summary = {"added": 0, "deleted": 0, "modified": 0, "errors": 0, "skipped": 0}

        # Step 1: Scan disk
        disk_files = self._scanner.scan_all_files()

        # Step 2: Get indexed paths from vector store
        indexed_paths = await self._vector_store.list_all_note_paths()

        # Step 3: Compute diff
        diff = self._scanner.compute_diff(disk_files, indexed_paths)

        # No changes
        if not diff.added and not diff.deleted and not diff.modified:
            return summary

        # Step 4: Process deletions (fast, no API calls)
        for path in diff.deleted:
            try:
                await self._vector_store.delete_by_note_path(path)
                summary["deleted"] += 1
            except Exception as e:
                logger.error(f"Failed to delete vectors for {path}: {e}")
                summary["errors"] += 1

        # Step 5: Process additions and modifications (batched, costs API tokens)
        paths_to_embed = diff.added + diff.modified
        processed = 0

        for path in paths_to_embed:
            if processed >= self._batch_limit:
                logger.info(
                    f"Batch limit reached ({self._batch_limit}), "
                    f"remaining {len(paths_to_embed) - processed} files deferred to next cycle"
                )
                break

            # Skip files being processed by organize pipeline
            if path in self._skip_paths:
                logger.debug(f"Skipping {path} (being organized)")
                summary["skipped"] += 1
                continue

            try:
                await self._process_file(path)
                self._scanner.mark_synced(path)

                if path in diff.added:
                    summary["added"] += 1
                else:
                    summary["modified"] += 1
                processed += 1
            except Exception as e:
                logger.error(f"Failed to sync {path}: {e}")
                summary["errors"] += 1

        logger.info(
            f"Sync cycle complete: +{summary['added']} -{summary['deleted']} "
            f"~{summary['modified']} errors={summary['errors']} skipped={summary['skipped']}"
        )
        return summary

    async def _process_file(self, rel_path: str) -> None:
        """Read a file, chunk it, and embed+store its vectors.

        Args:
            rel_path: Relative path from notes root.
        """
        from pathlib import Path

        file_path = Path(self._config.note_storage.root_path) / rel_path

        # Read file content
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            logger.debug(f"Skipping empty file: {rel_path}")
            return

        # Extract a title from the first heading or filename
        title = self._extract_title(content, rel_path)

        # Chunk the content
        chunks = chunk_markdown(
            content,
            max_chunk_tokens=self._config.chunking.max_chunk_tokens,
            overlap_tokens=self._config.chunking.overlap_tokens,
        )

        if not chunks:
            logger.debug(f"No chunks produced for: {rel_path}")
            return

        # Embed and store (Embedder handles delete-then-insert internally)
        count = await self._embedder.embed_and_store(
            note_path=rel_path,
            note_title=title,
            chunks=chunks,
        )
        logger.info(f"Synced {rel_path}: {count} chunks embedded")

    async def _full_rebuild(self) -> dict:
        """Clear all vectors and rebuild from all files on disk.

        Returns:
            Summary dict.
        """
        summary = {"processed": 0, "errors": 0}

        logger.warning("Starting full vector store rebuild...")

        # Clear the entire collection
        await self._vector_store.delete_all()

        # Scan and process all files
        disk_files = self._scanner.scan_all_files()
        total = len(disk_files)

        for i, rel_path in enumerate(sorted(disk_files.keys())):
            try:
                await self._process_file(rel_path)
                self._scanner.mark_synced(rel_path)
                summary["processed"] += 1
                if (i + 1) % 10 == 0:
                    logger.info(f"Rebuild progress: {i + 1}/{total}")
            except Exception as e:
                logger.error(f"Failed to rebuild {rel_path}: {e}")
                summary["errors"] += 1

        logger.info(
            f"Full rebuild complete: {summary['processed']}/{total} files, "
            f"{summary['errors']} errors"
        )
        return summary

    @staticmethod
    def _extract_title(content: str, rel_path: str) -> str:
        """Extract a title from Markdown content or fall back to filename.

        Args:
            content: Markdown content.
            rel_path: Relative file path for fallback.

        Returns:
            Extracted title string.
        """
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# ") and not line.startswith("##"):
                return line[2:].strip()

        # Fallback: use filename without extension
        from pathlib import Path

        return Path(rel_path).stem
