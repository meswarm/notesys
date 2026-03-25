"""Unified LLM client wrapping DashScope APIs.

Handles:
- Text chat via DashScope MultiModalConversation (qwen3.5/qwen3-vl series)
- Text embedding via DashScope TextEmbedding (text-embedding-v4)
- Automatic token usage tracking
- Retry with exponential backoff
"""

import os
import time
from typing import Any, Optional

import dashscope
from dashscope import MultiModalConversation, TextEmbedding
from loguru import logger
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import ModelConfig
from src.core.usage_tracker import TokenUsage, UsageTracker


class LLMResponse(BaseModel):
    """Standardized response from LLM calls."""

    content: str = ""
    reasoning_content: str = ""
    raw_response: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResult(BaseModel):
    """Result from embedding API call."""

    embeddings: list[dict[str, Any]] = []
    total_tokens: int = 0


class LLMClient:
    """Unified client for all LLM API calls.

    All model calls go through this class, which handles:
    - Provider-specific API differences
    - Token usage tracking
    - Retry logic
    """

    def __init__(self, api_key: str, usage_tracker: Optional[UsageTracker] = None):
        """Initialize LLM client.

        Args:
            api_key: DashScope API key.
            usage_tracker: Optional usage tracker for recording token consumption.
        """
        self._api_key = api_key
        self._usage_tracker = usage_tracker or UsageTracker()

        # Set DashScope API key globally
        dashscope.api_key = api_key

    @property
    def usage_tracker(self) -> UsageTracker:
        return self._usage_tracker

    async def chat(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        step: str = "unknown",
        **kwargs,
    ) -> LLMResponse:
        """Send a chat request to the LLM.

        Uses DashScope MultiModalConversation API for qwen3.5/qwen3-vl models.

        Args:
            model_config: Model configuration.
            messages: List of message dicts with 'role' and 'content'.
            step: Pipeline step name (for tracking).
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content and token usage.
        """
        start_time = time.time()

        try:
            response = await self._call_multimodal_chat(model_config, messages, **kwargs)
        except Exception as e:
            logger.error(f"LLM chat call failed for step '{step}': {e}")
            raise

        latency_ms = (time.time() - start_time) * 1000

        # Parse response
        llm_response = self._parse_chat_response(response, model_config)

        # Track usage
        usage = TokenUsage(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            model=model_config.model,
            step=step,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            total_tokens=llm_response.total_tokens,
            latency_ms=latency_ms,
            cost=self._estimate_cost(model_config.model, llm_response.input_tokens, llm_response.output_tokens),
        )
        await self._usage_tracker.record(usage)

        return llm_response

    async def chat_with_retry(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        step: str = "unknown",
        max_retries: int = 3,
        **kwargs,
    ) -> LLMResponse:
        """Chat with automatic retry on failure.

        Args:
            model_config: Model configuration.
            messages: Message list.
            step: Pipeline step name.
            max_retries: Maximum number of retry attempts.
            **kwargs: Additional API parameters.

        Returns:
            LLMResponse on success.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self.chat(model_config, messages, step=step, **kwargs)
            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    f"Chat attempt {attempt + 1}/{max_retries} failed for step '{step}': {e}. "
                    f"Retrying in {wait_time}s..."
                )
                import asyncio
                await asyncio.sleep(wait_time)

        raise RuntimeError(
            f"Chat failed after {max_retries} attempts for step '{step}': {last_error}"
        )

    async def embed(
        self,
        texts: list[str],
        text_type: str = "document",
        output_type: str = "dense&sparse",
        dimension: int = 1024,
        step: str = "embedding",
        instruct: Optional[str] = None,
    ) -> EmbeddingResult:
        """Generate embeddings using DashScope TextEmbedding API.

        Args:
            texts: List of texts to embed (max 10 per batch).
            text_type: 'document' for storage, 'query' for retrieval.
            output_type: 'dense', 'sparse', or 'dense&sparse'.
            dimension: Vector dimension (default 1024).
            step: Pipeline step name (for tracking).
            instruct: Optional task instruction (English) for query optimization.

        Returns:
            EmbeddingResult with embeddings and token usage.
        """
        start_time = time.time()

        try:
            result = await self._call_embedding(
                texts, text_type, output_type, dimension, instruct
            )
        except Exception as e:
            logger.error(f"Embedding call failed for step '{step}': {e}")
            raise

        latency_ms = (time.time() - start_time) * 1000

        # Track usage
        total_tokens = result.get("total_tokens", 0)
        usage = TokenUsage(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            model="text-embedding-v4",
            step=step,
            input_tokens=total_tokens,
            output_tokens=0,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost=total_tokens * 0.0005 / 1000,  # 0.0005 元 per 1000 tokens
        )
        await self._usage_tracker.record(usage)

        return EmbeddingResult(
            embeddings=result.get("embeddings", []),
            total_tokens=total_tokens,
        )

    async def embed_with_retry(
        self,
        texts: list[str],
        text_type: str = "document",
        output_type: str = "dense&sparse",
        dimension: int = 1024,
        step: str = "embedding",
        instruct: Optional[str] = None,
        max_retries: int = 3,
    ) -> EmbeddingResult:
        """Embed with automatic retry."""
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self.embed(
                    texts, text_type, output_type, dimension, step, instruct
                )
            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(
                    f"Embed attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                import asyncio
                await asyncio.sleep(wait_time)

        raise RuntimeError(f"Embedding failed after {max_retries} attempts: {last_error}")

    # ---- Private methods ----

    async def _call_multimodal_chat(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> Any:
        """Call DashScope MultiModalConversation API.

        This is used for qwen3.5 and qwen3-vl series models.
        Runs synchronous SDK call in an executor to avoid blocking the event loop.
        """
        import asyncio

        def _sync_call():
            call_kwargs = {
                "api_key": self._api_key,
                "model": model_config.model,
                "messages": messages,
                "max_tokens": model_config.max_tokens,
            }

            # Add temperature if not thinking mode
            if not model_config.enable_thinking:
                call_kwargs["temperature"] = model_config.temperature

            # Add thinking mode parameter
            if model_config.enable_thinking:
                call_kwargs["enable_thinking"] = True

            # Merge any additional kwargs
            call_kwargs.update(kwargs)

            return MultiModalConversation.call(**call_kwargs)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_call)

    def _parse_chat_response(self, response: Any, model_config: ModelConfig) -> LLMResponse:
        """Parse DashScope MultiModalConversation response."""
        if response.status_code != 200:
            raise RuntimeError(
                f"DashScope API error: status={response.status_code}, "
                f"code={response.code}, message={response.message}"
            )

        message = response.output.choices[0].message

        # Extract content
        content = ""
        if isinstance(message.content, list):
            # MultiModal response format: [{"text": "..."}]
            for item in message.content:
                if isinstance(item, dict) and "text" in item:
                    content += item["text"]
        elif isinstance(message.content, str):
            content = message.content

        # Extract reasoning content (for thinking mode)
        reasoning_content = getattr(message, "reasoning_content", "") or ""

        # Extract token usage
        usage = getattr(response, "usage", None)
        input_tokens = 0
        output_tokens = 0
        if usage:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0

        return LLMResponse(
            content=content,
            reasoning_content=reasoning_content,
            raw_response=response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    async def _call_embedding(
        self,
        texts: list[str],
        text_type: str,
        output_type: str,
        dimension: int,
        instruct: Optional[str],
    ) -> dict:
        """Call DashScope TextEmbedding API.

        Must use DashScope SDK (not OpenAI compatible) for text_type,
        output_type, and instruct parameters.
        """
        import asyncio

        def _sync_call():
            call_kwargs = {
                "model": "text-embedding-v4",
                "input": texts,
                "dimension": dimension,
                "text_type": text_type,
                "output_type": output_type,
                "api_key": self._api_key,
            }

            if instruct and text_type == "query":
                call_kwargs["instruct"] = instruct

            return TextEmbedding.call(**call_kwargs)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _sync_call)

        if response.status_code != 200:
            raise RuntimeError(
                f"Embedding API error: status={response.status_code}, "
                f"code={response.code}, message={response.message}"
            )

        # Parse response - normalize sparse embedding format
        raw_embeddings = response.output.get("embeddings", [])
        total_tokens = response.usage.get("total_tokens", 0)

        # Normalize sparse_embedding from DashScope format:
        #   list[{index: int, token: str, value: float}]
        # to Qdrant format:
        #   {indices: list[int], values: list[float]}
        normalized_embeddings = []
        for emb in raw_embeddings:
            normalized = dict(emb)
            sparse = emb.get("sparse_embedding", None)
            if sparse and isinstance(sparse, list):
                indices = [item["index"] for item in sparse if "index" in item]
                values = [item["value"] for item in sparse if "value" in item]
                normalized["sparse_embedding"] = {
                    "indices": indices,
                    "values": values,
                }
            normalized_embeddings.append(normalized)

        return {"embeddings": normalized_embeddings, "total_tokens": total_tokens}

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate API call cost based on model pricing.

        Pricing (per 1000 tokens, in RMB):
        - qwen3-vl-flash: input 0.0008, output 0.0032 (non-thinking)
        - qwen3.5-flash:  input 0.0008, output 0.0032 (non-thinking)
        - qwen3.5-plus:   input 0.0015, output 0.006
        - text-embedding-v4: input 0.0005
        """
        pricing = {
            "qwen3-vl-flash": (0.0008, 0.0032),
            "qwen3.5-flash": (0.0008, 0.0032),
            "qwen3.5-plus": (0.0015, 0.006),
            "text-embedding-v4": (0.0005, 0.0),
        }

        rates = pricing.get(model, (0.001, 0.004))  # Default fallback
        cost = (input_tokens * rates[0] + output_tokens * rates[1]) / 1000
        return round(cost, 6)
