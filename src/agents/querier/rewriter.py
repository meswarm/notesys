"""Query rewriting using LLM for better retrieval."""

from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import BaseModel

from src.core.config import ModelConfig
from src.core.retry import validate_json_output
from src.llm.client import LLMClient


class RewriteResult(BaseModel):
    """Result of query rewriting."""

    rewritten_query: str
    keywords: list[str] = []
    intent: str = ""


class QueryRewriter:
    """Rewrites user queries for better retrieval performance."""

    def __init__(self, llm_client: LLMClient, model_config: ModelConfig):
        self._llm = llm_client
        self._config = model_config
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path("src/llm/prompts/query_rewrite.txt")
        return prompt_path.read_text(encoding="utf-8")

    async def rewrite(
        self,
        user_query: str,
        max_retries: int = 2,
    ) -> RewriteResult:
        """Rewrite a user query for better retrieval.

        Args:
            user_query: Original user query.
            max_retries: Maximum retry attempts.

        Returns:
            RewriteResult with rewritten query, keywords, and intent.
        """
        messages = [
            {"role": "system", "content": [{"text": self._system_prompt}]},
            {"role": "user", "content": [{"text": user_query}]},
        ]

        response = await self._llm.chat_with_retry(
            model_config=self._config,
            messages=messages,
            step="query_rewrite",
            max_retries=max_retries,
            timeout=60,
            response_format={"type": "json_object"},
        )

        parsed = validate_json_output(response.content)
        if parsed:
            result = RewriteResult(
                rewritten_query=parsed.get("rewritten_query", user_query),
                keywords=parsed.get("keywords", []),
                intent=parsed.get("intent", ""),
            )
            logger.info(f"Query rewritten: '{user_query}' -> '{result.rewritten_query}'")
            return result

        # Fallback: use original query
        logger.warning("Query rewrite failed, using original query")
        return RewriteResult(rewritten_query=user_query)
