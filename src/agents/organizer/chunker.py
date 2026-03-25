"""Markdown text chunking for vector storage."""

import re
from typing import Optional

from src.models.note import NoteChunk


def chunk_markdown(
    content: str,
    max_chunk_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[NoteChunk]:
    """Split Markdown content into chunks by headings and paragraphs.

    Strategy:
    1. Split by headings (##, ###)
    2. If a section is too long, split by paragraphs
    3. Each chunk records its heading context

    Args:
        content: Markdown text to chunk.
        max_chunk_tokens: Maximum tokens per chunk (approximate, using char/2 heuristic).
        overlap_tokens: Overlap between chunks for context continuity.

    Returns:
        List of NoteChunk objects.
    """
    # Approximate max chars (Chinese ≈ 1 token per char, English ≈ 0.75 tokens per word)
    max_chars = max_chunk_tokens * 2  # Conservative estimate
    overlap_chars = overlap_tokens * 2

    # Split content by headings
    sections = _split_by_headings(content)

    chunks = []
    chunk_index = 0

    for heading, section_text in sections:
        if not section_text.strip():
            continue

        if len(section_text) <= max_chars:
            # Section fits in one chunk
            chunks.append(NoteChunk(
                chunk_index=chunk_index,
                heading=heading,
                text=f"{heading}\n\n{section_text}".strip() if heading else section_text.strip(),
            ))
            chunk_index += 1
        else:
            # Section too long, split by paragraphs
            paragraphs = section_text.split("\n\n")
            current_chunk = ""

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                if len(current_chunk) + len(para) + 2 <= max_chars:
                    current_chunk += ("\n\n" + para) if current_chunk else para
                else:
                    # Save current chunk
                    if current_chunk:
                        chunk_text = f"{heading}\n\n{current_chunk}".strip() if heading else current_chunk.strip()
                        chunks.append(NoteChunk(
                            chunk_index=chunk_index,
                            heading=heading,
                            text=chunk_text,
                        ))
                        chunk_index += 1

                    # Start new chunk with overlap
                    if overlap_chars > 0 and current_chunk:
                        overlap = current_chunk[-overlap_chars:]
                        current_chunk = overlap + "\n\n" + para
                    else:
                        current_chunk = para

            # Don't forget the last chunk
            if current_chunk.strip():
                chunk_text = f"{heading}\n\n{current_chunk}".strip() if heading else current_chunk.strip()
                chunks.append(NoteChunk(
                    chunk_index=chunk_index,
                    heading=heading,
                    text=chunk_text,
                ))
                chunk_index += 1

    # If no chunks were created (e.g., very short content), use the whole content
    if not chunks and content.strip():
        chunks.append(NoteChunk(
            chunk_index=0,
            heading="",
            text=content.strip(),
        ))

    return chunks


def _split_by_headings(content: str) -> list[tuple[str, str]]:
    """Split Markdown content by headings.

    Returns:
        List of (heading, section_content) tuples.
    """
    # Pattern matches ## and ### headings
    heading_pattern = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)

    sections = []
    matches = list(heading_pattern.finditer(content))

    if not matches:
        # No headings found, return entire content as one section
        return [("", content)]

    # Content before first heading
    if matches[0].start() > 0:
        pre_content = content[:matches[0].start()].strip()
        if pre_content:
            sections.append(("", pre_content))

    # Each heading and its content
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_content = content[start:end].strip()
        sections.append((heading, section_content))

    return sections
