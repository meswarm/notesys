"""File manager with atomic writes and directory-level locking."""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import aiofiles
from loguru import logger


class FileManager:
    """Manages note file storage with safety guarantees.

    Features:
    - Atomic writes (tmp file + rename) to prevent corruption
    - Directory-level asyncio locks for concurrent safety
    - Strict 2-level directory depth enforcement
    """

    def __init__(self, root_path: str, max_depth: int = 2):
        """Initialize file manager.

        Args:
            root_path: Root directory for note storage.
            max_depth: Maximum directory nesting depth (default 2).
        """
        self._root = Path(root_path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_depth = max_depth
        self._dir_locks: dict[str, asyncio.Lock] = {}

    @property
    def root_path(self) -> Path:
        return self._root

    def _get_lock(self, dir_path: str) -> asyncio.Lock:
        """Get or create a lock for the given directory."""
        if dir_path not in self._dir_locks:
            self._dir_locks[dir_path] = asyncio.Lock()
        return self._dir_locks[dir_path]

    def ensure_directory(self, category: str, subcategory: str) -> Path:
        """Ensure category/subcategory directory exists.

        Args:
            category: Top-level category (e.g., "操作系统").
            subcategory: Sub-category (e.g., "Linux").

        Returns:
            Path to the subcategory directory.
        """
        category = self._sanitize_path_component(category)
        subcategory = self._sanitize_path_component(subcategory)
        dir_path = self._root / category / subcategory
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    async def safe_write(
        self,
        category: str,
        subcategory: str,
        filename: str,
        content: str,
    ) -> str:
        """Atomically write a note file.

        Uses tmp file + rename for crash safety. Directory-level lock
        prevents concurrent writes to the same directory.

        Args:
            category: Top-level category.
            subcategory: Sub-category.
            filename: Filename (e.g., "ubuntu-安装指南.md").
            content: File content.

        Returns:
            Relative path from root to the saved file.
        """
        target_dir = self.ensure_directory(category, subcategory)
        dir_key = str(target_dir)
        lock = self._get_lock(dir_key)

        async with lock:
            # Ensure filename ends with .md
            if not filename.endswith(".md"):
                filename += ".md"

            # Sanitize filename
            filename = self._sanitize_filename(filename)

            # Deduplicate: if file already exists, append _2, _3, etc.
            stem = filename[:-3]  # remove .md
            final_path = target_dir / filename
            counter = 2
            while final_path.exists():
                filename = f"{stem}_{counter}.md"
                final_path = target_dir / filename
                counter += 1

            tmp_path = target_dir / f".tmp_{filename}"

            try:
                async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                    await f.write(content)
                # Atomic rename
                os.rename(tmp_path, final_path)
                logger.info(f"Note saved: {final_path}")
            except Exception as e:
                # Clean up tmp file on failure
                if tmp_path.exists():
                    tmp_path.unlink()
                raise RuntimeError(f"Failed to save note to {final_path}: {e}")

        return str(final_path.relative_to(self._root))

    async def read_file(self, relative_path: str) -> str:
        """Read a note file by its relative path.

        Args:
            relative_path: Path relative to the notes root directory.

        Returns:
            File content as string.
        """
        file_path = self._root / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"Note not found: {file_path}")

        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            return await f.read()

    async def copy_file(self, src: str, dst_dir: str, dst_filename: Optional[str] = None) -> str:
        """Copy a file (e.g., image) to a target directory.

        Args:
            src: Source file path (absolute or relative).
            dst_dir: Destination directory path.
            dst_filename: Optional new filename. If None, uses original name.

        Returns:
            Path to the copied file.
        """
        src_path = Path(src)
        if not src_path.exists():
            raise FileNotFoundError(f"Source file not found: {src}")

        dst_path = Path(dst_dir)
        dst_path.mkdir(parents=True, exist_ok=True)

        filename = dst_filename or src_path.name
        target = dst_path / filename

        shutil.copy2(str(src_path), str(target))
        return str(target)

    async def list_directories(self) -> dict[str, list[str]]:
        """List the current directory structure.

        Returns:
            Dictionary mapping categories to their subcategories.
        """
        result: dict[str, list[str]] = {}
        if not self._root.exists():
            return result

        for category_dir in sorted(self._root.iterdir()):
            if category_dir.is_dir() and not category_dir.name.startswith("."):
                subcategories = []
                for sub_dir in sorted(category_dir.iterdir()):
                    if sub_dir.is_dir() and not sub_dir.name.startswith("."):
                        subcategories.append(sub_dir.name)
                result[category_dir.name] = subcategories

        return result

    async def list_notes(self, category: str = "", subcategory: str = "") -> list[str]:
        """List note files, optionally filtered by category.

        Args:
            category: Optional category filter.
            subcategory: Optional subcategory filter.

        Returns:
            List of relative paths to note files.
        """
        notes = []
        search_root = self._root

        if category:
            search_root = self._root / category
            if subcategory:
                search_root = search_root / subcategory

        if not search_root.exists():
            return notes

        for md_file in search_root.rglob("*.md"):
            notes.append(str(md_file.relative_to(self._root)))

        return sorted(notes)

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename by removing unsafe characters.

        Args:
            filename: Raw filename.

        Returns:
            Sanitized filename.
        """
        # Replace path separators and other unsafe chars
        unsafe_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        return filename

    def _sanitize_path_component(self, name: str) -> str:
        """Sanitize one directory component generated by the classifier."""
        sanitized = self._sanitize_filename(name.strip())
        sanitized = re.sub(r"[\x00-\x1f]", "_", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        sanitized = sanitized.strip(".")
        return sanitized or "_"
