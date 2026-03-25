"""File scanner for detecting note changes against the vector store."""

import hashlib
import os
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import BaseModel


class FileFingerprint(BaseModel):
    """Fingerprint of a single note file for change detection."""

    path: str  # Relative path from notes root
    mtime: float  # Last modification time
    size: int  # File size in bytes
    content_hash: str = ""  # SHA-256 hash (computed on demand)


class SyncDiff(BaseModel):
    """Result of comparing disk files against vector store."""

    added: list[str] = []  # Paths on disk but not in vector store
    deleted: list[str] = []  # Paths in vector store but not on disk
    modified: list[str] = []  # Paths on both sides but content changed


class FileScanner:
    """Scans the notes root directory and detects file changes.

    Uses a two-stage change detection strategy:
    1. Fast filter: mtime + size comparison against last known state
    2. Accurate confirm: SHA-256 content hash for candidates
    """

    def __init__(self, root_path: str, min_depth: int = 0):
        self._root = Path(root_path)
        self._min_depth = min_depth
        # Cache of last-seen fingerprints for mtime/size fast-path
        self._last_fingerprints: dict[str, FileFingerprint] = {}

    def scan_all_files(self) -> dict[str, FileFingerprint]:
        """Scan all .md files under the notes root.

        Files shallower than min_depth are excluded.
        Depth 0 = directly in root, depth 1 = one subdirectory deep, etc.

        Returns:
            Mapping of relative path → FileFingerprint.
        """
        fingerprints: dict[str, FileFingerprint] = {}

        if not self._root.exists():
            logger.warning(f"Notes root does not exist: {self._root}")
            return fingerprints

        for md_file in self._root.rglob("*.md"):
            if md_file.name.startswith("."):
                continue

            rel_path = str(md_file.relative_to(self._root))
            # Check depth: count path separators
            depth = rel_path.count(os.sep)
            if depth < self._min_depth:
                continue

            try:
                stat = md_file.stat()
                fingerprints[rel_path] = FileFingerprint(
                    path=rel_path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                )
            except OSError as e:
                logger.warning(f"Failed to stat file {md_file}: {e}")

        return fingerprints

    def compute_diff(
        self,
        disk_files: dict[str, FileFingerprint],
        indexed_paths: set[str],
    ) -> SyncDiff:
        """Compute the difference between disk state and vector store state.

        Args:
            disk_files: Current files on disk (from scan_all_files).
            indexed_paths: Set of note_path values currently in the vector store.

        Returns:
            SyncDiff with added, deleted, and modified file lists.
        """
        disk_paths = set(disk_files.keys())

        added = list(disk_paths - indexed_paths)
        deleted = list(indexed_paths - disk_paths)

        # Check for modifications among files that exist on both sides
        modified = []
        common_paths = disk_paths & indexed_paths
        for path in common_paths:
            current = disk_files[path]
            last = self._last_fingerprints.get(path)

            if last is None:
                # First time seeing this file since service started,
                # compute content hash and mark as modified to ensure freshness
                current.content_hash = self._compute_hash(path)
                modified.append(path)
            elif current.mtime != last.mtime or current.size != last.size:
                # mtime or size changed — compute hash to confirm real change
                current.content_hash = self._compute_hash(path)
                if current.content_hash != last.content_hash:
                    modified.append(path)
                # else: file was touched but content didn't change, skip

        # Update cache with current fingerprints
        for path, fp in disk_files.items():
            if not fp.content_hash and path not in modified:
                # For unchanged files, preserve the old hash
                old = self._last_fingerprints.get(path)
                if old:
                    fp.content_hash = old.content_hash
            self._last_fingerprints[path] = fp

        # Clean up deleted files from cache
        for path in deleted:
            self._last_fingerprints.pop(path, None)

        logger.info(
            f"Sync diff: +{len(added)} added, -{len(deleted)} deleted, "
            f"~{len(modified)} modified (total {len(disk_files)} files on disk)"
        )

        return SyncDiff(added=added, deleted=deleted, modified=modified)

    def _compute_hash(self, rel_path: str) -> str:
        """Compute SHA-256 hash of file content.

        Args:
            rel_path: Path relative to notes root.

        Returns:
            Hex digest string, or empty string on error.
        """
        file_path = self._root / rel_path
        try:
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for block in iter(lambda: f.read(8192), b""):
                    sha256.update(block)
            return sha256.hexdigest()
        except OSError as e:
            logger.warning(f"Failed to hash file {file_path}: {e}")
            return ""

    def mark_synced(self, rel_path: str) -> None:
        """Update the fingerprint cache for a successfully synced file.

        Call this after a file has been re-embedded so subsequent scans
        won't treat it as modified again.

        Args:
            rel_path: Relative path of the synced file.
        """
        file_path = self._root / rel_path
        try:
            stat = file_path.stat()
            content_hash = self._compute_hash(rel_path)
            self._last_fingerprints[rel_path] = FileFingerprint(
                path=rel_path,
                mtime=stat.st_mtime,
                size=stat.st_size,
                content_hash=content_hash,
            )
        except OSError as e:
            logger.warning(f"Failed to update fingerprint for {rel_path}: {e}")
