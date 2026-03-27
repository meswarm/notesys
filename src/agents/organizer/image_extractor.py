"""Image semantic extraction from Markdown notes.

Uses multi-modal LLM (qwen3-vl-flash) to generate semantic descriptions
for images referenced in Markdown content.

Strategy: process each image individually, send the image together with its
surrounding Markdown context, and let the model return a plain-text
description. We then insert that description into the ![...] alt text
ourselves — no structured JSON required from the model.
"""

import re
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from src.core.config import ModelConfig
from src.llm.client import LLMClient

# Number of Markdown lines before/after the image to include as context
_CONTEXT_LINES = 8


class ImageExtractor:
    """Extracts semantic descriptions for images in Markdown notes."""

    def __init__(self, llm_client: LLMClient, model_config: ModelConfig):
        self._llm = llm_client
        self._config = model_config
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path("src/llm/prompts/image_semantic.txt")
        return prompt_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    async def extract(
        self,
        markdown_content: str,
        images_dir: Optional[str] = None,
        event_callback: Optional[Callable] = None,
        max_retries: int = 2,
    ) -> str:
        """Extract semantic descriptions for all images and fill in alt text.

        Args:
            markdown_content: Raw Markdown content with image references.
            images_dir: Base directory for resolving relative image paths.
            event_callback: Optional progress callback (unused here).
            max_retries: Retry count per image.

        Returns:
            Updated Markdown with semantic ALT text filled in.
        """
        images = self._find_images(markdown_content)
        if not images:
            logger.info("No images found in Markdown content")
            return markdown_content

        logger.info(f"Found {len(images)} images to process")

        lines = markdown_content.splitlines()
        updated_content = markdown_content
        processed = 0

        for img in images:
            img_path = img["path"]
            line_idx = img["line"]

            # Resolve to an absolute local path or URL
            file_uri = self._resolve_image_uri(img_path, images_dir)
            if not file_uri:
                logger.warning(f"Image not accessible, skipping: {img_path}")
                continue

            # Extract surrounding context lines
            context = self._extract_context(lines, line_idx)

            # Build the image reference string for the prompt
            image_reference = f"![{img['alt']}]({img_path})"

            # Ask the VL model for a description
            description = await self._describe_image(
                file_uri, image_reference, context, max_retries
            )
            if not description:
                logger.warning(f"Empty description for image: {img_path}")
                continue

            # Replace alt text in Markdown (preserve original path + optional title)
            escaped_path = re.escape(img_path)
            title_suffix = img.get("title", "")
            if title_suffix:
                escaped_suffix = re.escape(f' "{title_suffix}"')
                pattern = rf"!\[[^\]]*\]\({escaped_path}{escaped_suffix}\)"
                new_text = f'![{description}]({img_path} "{title_suffix}")'
            else:
                pattern = rf"!\[[^\]]*\]\({escaped_path}\)"
                new_text = f"![{description}]({img_path})"
            new_content = re.sub(pattern, lambda _: new_text, updated_content, count=1)

            if new_content != updated_content:
                processed += 1
                updated_content = new_content
            else:
                logger.warning(f"Failed to replace alt text for: {img_path}")

        logger.info(f"Updated ALT text for {processed}/{len(images)} images")
        return updated_content

    # ------------------------------------------------------------------ #
    #  Private helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_images(markdown_content: str) -> list[dict]:
        """Find all image references with their line numbers.

        Handles optional Markdown title attribute:
            ![alt](path)              → path only
            ![alt](path "title")      → path + title separated
        """
        # Group 1: alt text, Group 2: path (no quotes/spaces), Group 3: optional title
        pattern = re.compile(r'!\[([^\]]*)\]\((\S+?)(?:\s+"([^"]*)")?\)')
        images = []
        for idx, line in enumerate(markdown_content.splitlines()):
            for m in pattern.finditer(line):
                entry = {
                    "alt": m.group(1),
                    "path": m.group(2),
                    "line": idx,
                }
                if m.group(3) is not None:
                    entry["title"] = m.group(3)
                images.append(entry)
        return images

    @staticmethod
    def _resolve_image_uri(
        img_path: str, images_dir: Optional[str]
    ) -> Optional[str]:
        """Resolve an image path to a file URI or URL."""
        if img_path.startswith(("http://", "https://")):
            return img_path

        if images_dir:
            full_path = Path(images_dir) / img_path
            if full_path.exists():
                return f"file://{full_path.resolve()}"
        return None

    @staticmethod
    def _extract_context(
        lines: list[str], image_line: int, window: int = _CONTEXT_LINES
    ) -> str:
        """Get surrounding lines as context for the model."""
        start = max(0, image_line - window)
        end = min(len(lines), image_line + window + 1)
        return "\n".join(lines[start:end])

    async def _describe_image(
        self,
        image_uri: str,
        image_reference: str,
        context: str,
        max_retries: int,
    ) -> str:
        """Call multi-modal LLM to describe a single image."""
        prompt_text = (
            self._prompt_template
            .replace("{image_reference}", image_reference)
            .replace("{context}", context)
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"image": image_uri},
                    {"text": prompt_text},
                ],
            }
        ]

        response = await self._llm.chat_with_retry(
            model_config=self._config,
            messages=messages,
            step="image_semantic",
            max_retries=max_retries,
        )

        # Clean up: strip quotes, whitespace, markdown wrappers
        text = response.content.strip().strip('"').strip("'").strip()
        # Remove possible markdown code block wrapper
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return text.strip()
