"""Note classification using LLM with category enumeration."""

import re
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from src.core.config import ModelConfig
from src.core.retry import validate_json_output, build_format_retry_prompt
from src.llm.client import LLMClient
from src.models.note import ClassificationResult


class NoteClassifier:
    """Classifies notes into categories with hot-reload and auto-save support.

    Categories are loaded from YAML file on every classify() call,
    and new LLM-recommended categories are written back to the file.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model_config: ModelConfig,
        categories_path: str = "config/categories.yaml",
    ):
        self._llm = llm_client
        self._config = model_config
        self._categories_path = Path(categories_path)
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path("src/llm/prompts/note_classify.txt")
        return prompt_path.read_text(encoding="utf-8")

    def _load_categories(self) -> dict[str, list[str]]:
        """Load categories from YAML file (hot-reload on every call)."""
        if not self._categories_path.exists():
            logger.warning(f"Categories file not found: {self._categories_path}")
            return {}
        with open(self._categories_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        categories = data.get("categories", {})
        logger.debug(f"Loaded {sum(len(v) for v in categories.values())} subcategories from {self._categories_path}")
        return categories

    def _save_new_category(self, category: str, subcategory: str) -> None:
        """Append a new category/subcategory to the YAML file."""
        categories = self._load_categories()

        # Check if already exists (race condition guard)
        if category in categories and subcategory in categories[category]:
            return

        # Add new entry
        if category not in categories:
            categories[category] = [subcategory]
        else:
            categories[category].append(subcategory)

        # Write back — preserve comment header
        content = "# config/categories.yaml\n# 笔记分类枚举表 - 模型优先从此表中选择\n\n"
        content += yaml.dump(
            {"categories": categories},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        self._categories_path.write_text(content, encoding="utf-8")
        logger.info(f"New category saved to {self._categories_path}: {category}/{subcategory}")

    def _format_categories_text(self, categories: dict[str, list[str]]) -> str:
        """Format categories into a readable text for the prompt."""
        lines = []
        for category, subcategories in categories.items():
            for sub in subcategories:
                lines.append(f"  - {category}/{sub}")
        return "\n".join(lines)

    def _validate_classification(
        self, result: dict, categories: dict[str, list[str]]
    ) -> bool:
        """Validate classification result and normalize category names.

        First tries to fuzzy-match against the predefined category table.
        If no match is found, accepts the LLM-recommended new category
        as long as all required fields are non-empty.

        Returns True if the result is usable (either matched or new).
        """
        category = result.get("category", "").strip()
        subcategory = result.get("subcategory", "").strip()
        title = result.get("title", "").strip()

        if not category or not subcategory or not title:
            return False

        norm = lambda s: re.sub(r"\s+", "", s)

        # Try fuzzy match against predefined category table
        for canon_cat, subs in categories.items():
            if norm(category) == norm(canon_cat):
                for canon_sub in subs:
                    if norm(subcategory) == norm(canon_sub):
                        # Write back canonical names
                        result["category"] = canon_cat
                        result["subcategory"] = canon_sub
                        result["title"] = title
                        result["is_new_category"] = False
                        return True

        # No match in predefined categories — accept as new category
        result["category"] = category
        result["subcategory"] = subcategory
        result["title"] = title
        result["is_new_category"] = True
        logger.info(f"New category recommended by LLM: {category}/{subcategory}")
        return True

    async def classify(
        self,
        markdown_content: str,
        max_retries: int = 3,
    ) -> ClassificationResult:
        """Classify a note into a category.

        Hot-reloads categories from YAML on every call. If the LLM suggests
        a new category, it is automatically saved to the YAML file.

        Args:
            markdown_content: Formatted note content.
            max_retries: Maximum retry attempts.

        Returns:
            ClassificationResult with category, subcategory, and title.
        """
        # Hot-reload categories from disk
        categories = self._load_categories()

        categories_text = self._format_categories_text(categories)
        prompt = (
            self._prompt_template
            .replace("{categories_text}", categories_text)
            .replace("{markdown_content}", markdown_content[:3000])
        )

        messages = [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ]

        for attempt in range(max_retries):
            response = await self._llm.chat_with_retry(
                model_config=self._config,
                messages=messages,
                step="note_classify",
                max_retries=2,
            )

            logger.info(f"Classifier raw response (attempt {attempt+1}): [{response.content[:500]}]")

            parsed = validate_json_output(response.content)
            logger.info(f"Classifier parsed JSON: {parsed}")

            if parsed and self._validate_classification(parsed, categories):
                is_new = parsed.get("is_new_category", False)
                result = ClassificationResult(
                    category=parsed["category"],
                    subcategory=parsed["subcategory"],
                    title=parsed["title"],
                )

                # Auto-save new category to YAML
                if is_new:
                    self._save_new_category(result.category, result.subcategory)
                    logger.info(f"Note classified (new category): {result.category}/{result.subcategory}/{result.title}")
                else:
                    logger.info(f"Note classified: {result.category}/{result.subcategory}/{result.title}")

                return result

            # Log failure reason
            if parsed:
                logger.warning(
                    f"Classification attempt {attempt + 1} failed validation: "
                    f"category='{parsed.get('category', '')}', "
                    f"subcategory='{parsed.get('subcategory', '')}', "
                    f"title='{parsed.get('title', '')}'"
                )
            else:
                logger.warning(
                    f"Classification attempt {attempt + 1}: JSON parsing failed. "
                    f"Raw response: [{response.content[:300]}]"
                )

            # Retry with enhanced prompt
            prompt = build_format_retry_prompt(
                prompt,
                '输出必须是 JSON: {"category": "分类名称", "subcategory": "子分类名称", "title": "简洁标题"}'
            )
            messages = [{"role": "user", "content": [{"text": prompt}]}]

        # Fallback
        logger.warning("Classification failed after all retries, falling back to uncategorized")
        return ClassificationResult(
            category="未分类",
            subcategory="未分类",
            title="untitled",
        )
