"""Note formatting and content reorganization."""

import re
from pathlib import Path
from typing import Optional

from loguru import logger

from src.core.config import ModelConfig
from src.llm.client import LLMClient


class NoteFormatter:
    """Formats and reorganizes note content using LLM."""

    def __init__(self, llm_client: LLMClient, model_config: ModelConfig):
        self._llm = llm_client
        self._config = model_config
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path("src/llm/prompts/note_format.txt")
        return prompt_path.read_text(encoding="utf-8")

    async def format(
        self,
        markdown_content: str,
        max_retries: int = 2,
    ) -> str:
        """Format and reorganize note content.

        Reorders content logically, removes redundancy, and normalizes formatting.

        Args:
            markdown_content: Raw or partially processed Markdown.
            max_retries: Maximum retry attempts.

        Returns:
            Formatted Markdown content.
        """
        protected_content, protected_spans = self._protect_immutable_markdown(
            markdown_content
        )
        messages = [
            {"role": "system", "content": [{"text": self._system_prompt}]},
            {"role": "user", "content": [{"text": protected_content}]},
        ]

        response = await self._llm.chat_with_retry(
            model_config=self._config,
            messages=messages,
            step="note_format",
            max_retries=max_retries,
            timeout=180,
        )

        formatted = response.content.strip()

        # Remove potential markdown wrapper if model adds ```markdown ... ```
        if formatted.startswith("```markdown"):
            formatted = formatted[len("```markdown"):].strip()
        if formatted.startswith("```"):
            formatted = formatted[3:].strip()
        if formatted.endswith("```"):
            formatted = formatted[:-3].strip()

        if protected_spans:
            missing = [
                token for token in protected_spans
                if token not in formatted
            ]
            if missing:
                logger.warning(
                    "Formatter dropped protected Markdown spans; "
                    "falling back to unformatted protected input"
                )
                formatted = protected_content
            formatted = self._restore_protected_spans(formatted, protected_spans)

        # Post-process: restore alt text from image-detail comments
        formatted = self._restore_image_alt_from_detail(formatted)

        logger.info(f"Note formatted: {len(markdown_content)} -> {len(formatted)} chars")
        return formatted

    @staticmethod
    def _protect_immutable_markdown(content: str) -> tuple[str, dict[str, str]]:
        """Replace precise Markdown spans with placeholders before LLM formatting.

        These spans often contain paths, URLs, commands, or exact syntax that should
        be moved as a unit but never rewritten by the model.
        """
        spans: dict[str, str] = {}
        protected = content

        patterns = [
            re.compile(r"```[\s\S]*?```"),
            re.compile(r"~~~[\s\S]*?~~~"),
            re.compile(r"!\[[^\]\n]*\]\([^)\n]+\)"),
            re.compile(r"(?<!!)\[[^\]\n]+\]\([^)\n]+\)"),
            re.compile(r"<https?://[^>\s]+>"),
            re.compile(r"(?<!\]\()https?://[^\s<>)]+"),
            re.compile(r"`[^`\n]+`"),
        ]

        def _store(match: re.Match) -> str:
            token = f"NOTESYS_PROTECTED_{len(spans):04d}"
            spans[token] = match.group(0)
            return token

        for pattern in patterns:
            protected = pattern.sub(_store, protected)

        return protected, spans

    @staticmethod
    def _restore_protected_spans(content: str, spans: dict[str, str]) -> str:
        """Restore placeholders created by _protect_immutable_markdown."""
        restored = content
        for token, original in spans.items():
            restored = restored.replace(token, original)
        return restored

    @staticmethod
    def _restore_image_alt_from_detail(content: str) -> str:
        """Move image-detail comment content into alt text and remove the comment.

        Finds patterns like:
            ![](path)\n<!-- image-detail: ... -->
            ![alt](path)\n\n<!-- image-detail: ... -->
        And transforms to:
            ![full detail](path)
        """
        # Pattern: ![any alt](path) followed by image-detail comment
        pattern = re.compile(
            r"(!\[)[^\]]*(\]\([^)]+\))"  # group1: "![", group2: "](path)"
            r"\s*\n\s*\n?\s*"             # optional blank lines between
            r"<!-- image-detail:\s*"       # comment opening
            r"(.*?)"                       # group3: detail content
            r"\s*-->",                     # comment closing
            re.DOTALL,
        )

        def _replacer(m: re.Match) -> str:
            detail = m.group(3).strip()
            return f"{m.group(1)}{detail}{m.group(2)}"

        return pattern.sub(_replacer, content)
