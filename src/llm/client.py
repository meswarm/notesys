"""Unified LLM client wrapping OpenAI-compatible and DashScope APIs.

Handles:
- Text chat via OpenAI-compatible API (streaming) for all qwen models
- Vision chat via OpenAI-compatible API (streaming) for qwen3-vl models
- Text embedding via DashScope TextEmbedding (text-embedding-v4)
  (DashScope SDK retained for text_type, sparse_embedding, instruct features)
- Automatic token usage tracking
- Configurable timeout per request
"""

import asyncio
import os
import time
from typing import Any, Optional

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

from src.core.config import ModelConfig
from src.core.usage_tracker import TokenUsage, UsageTracker

# DashScope base URL for OpenAI-compatible mode
_DASHSCOPE_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


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

    Chat calls use OpenAI-compatible API with streaming for lower latency.
    Embedding calls use DashScope SDK for text_type/sparse/instruct features.
    """

    def __init__(self, api_key: str, usage_tracker: Optional[UsageTracker] = None):
        """Initialize LLM client.

        Args:
            api_key: DashScope API key.
            usage_tracker: Optional usage tracker for recording token consumption.
        """
        self._api_key = api_key
        self._usage_tracker = usage_tracker or UsageTracker()

        # OpenAI-compatible async client for chat
        self._openai_client = AsyncOpenAI(
            api_key=api_key,
            base_url=_DASHSCOPE_OPENAI_BASE_URL,
        )

        # Set DashScope API key for embedding calls
        import dashscope
        dashscope.api_key = api_key

    @property
    def usage_tracker(self) -> UsageTracker:
        return self._usage_tracker

    async def chat(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        step: str = "unknown",
        timeout: float = 120,
        **kwargs,
    ) -> LLMResponse:
        """Send a streaming chat request via OpenAI-compatible API.

        Args:
            model_config: Model configuration.
            messages: List of message dicts (OpenAI format).
            step: Pipeline step name (for tracking).
            timeout: Request timeout in seconds (default 120s).
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content and token usage.
        """
        start_time = time.time()

        try:
            # Normalize messages to OpenAI format
            openai_messages = self._normalize_messages(messages)

            response = await self._stream_chat(
                model_config, openai_messages, timeout, **kwargs
            )
        except Exception as e:
            logger.error(f"LLM chat call failed for step '{step}': {e}")
            raise

        latency_ms = (time.time() - start_time) * 1000

        # Track usage
        usage = TokenUsage(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            model=model_config.model,
            step=step,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            latency_ms=latency_ms,
            cost=self._estimate_cost(
                model_config.model, response.input_tokens, response.output_tokens
            ),
        )
        await self._usage_tracker.record(usage)

        return response

    async def chat_with_retry(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        step: str = "unknown",
        max_retries: int = 3,
        timeout: float = 120,
        **kwargs,
    ) -> LLMResponse:
        """Chat with automatic retry on failure.

        Args:
            model_config: Model configuration.
            messages: Message list.
            step: Pipeline step name.
            max_retries: Maximum number of retry attempts.
            timeout: Per-request timeout in seconds.
            **kwargs: Additional API parameters.

        Returns:
            LLMResponse on success.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self.chat(
                    model_config, messages, step=step, timeout=timeout, **kwargs
                )
            except Exception as e:
                last_error = e
                wait_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    f"Chat attempt {attempt + 1}/{max_retries} failed for step '{step}': {e}. "
                    f"Retrying in {wait_time}s..."
                )
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

        DashScope SDK is retained here because the OpenAI-compatible API
        does not support text_type, output_type (sparse), or instruct params.

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
                wait_time = 2**attempt
                logger.warning(
                    f"Embed attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        raise RuntimeError(
            f"Embedding failed after {max_retries} attempts: {last_error}"
        )

    # ---- Private methods ----

    def _normalize_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Normalize messages from DashScope format to OpenAI format.

        DashScope format:
            {"role": "user", "content": [{"text": "..."}, {"image": "file://..."}]}
        OpenAI format:
            {"role": "user", "content": [{"type": "text", "text": "..."},
                                          {"type": "image_url", "image_url": {"url": "..."}}]}

        Also handles plain string content (already OpenAI compatible).
        """
        normalized = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Already a string — pass through
            if isinstance(content, str):
                normalized.append({"role": role, "content": content})
                continue

            # List of content parts — convert each
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, str):
                        parts.append({"type": "text", "text": item})
                    elif isinstance(item, dict):
                        if "text" in item:
                            parts.append({"type": "text", "text": item["text"]})
                        elif "image" in item:
                            # Convert DashScope image format to OpenAI image_url
                            image_url = item["image"]
                            # Handle local file:// URIs — convert to base64
                            if image_url.startswith("file://"):
                                base64_url = self._file_to_base64_url(image_url)
                                if base64_url:
                                    parts.append({
                                        "type": "image_url",
                                        "image_url": {"url": base64_url},
                                    })
                                else:
                                    logger.warning(
                                        f"Failed to read local image: {image_url}"
                                    )
                            else:
                                # HTTP/HTTPS URL — pass through
                                parts.append({
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                })
                        elif "type" in item:
                            # Already OpenAI format
                            parts.append(item)
                    else:
                        parts.append({"type": "text", "text": str(item)})
                normalized.append({"role": role, "content": parts})
            else:
                normalized.append({"role": role, "content": str(content)})

        return normalized

    @staticmethod
    def _file_to_base64_url(file_uri: str) -> Optional[str]:
        """Convert a file:// URI to a base64 data URL."""
        import base64
        import mimetypes
        from pathlib import Path

        file_path = Path(file_uri.replace("file://", ""))
        if not file_path.exists():
            return None

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "image/jpeg"  # fallback

        data = file_path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    async def _stream_chat(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        timeout: float = 120,
        **kwargs,
    ) -> LLMResponse:
        """Stream chat completion via OpenAI-compatible API.

        Collects all chunks into a complete response.
        """
        call_kwargs: dict[str, Any] = {
            "model": model_config.model,
            "messages": messages,
            "max_tokens": model_config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": timeout,
        }

        # Temperature (not used in thinking mode)
        if not model_config.enable_thinking:
            call_kwargs["temperature"] = model_config.temperature

        # Thinking mode
        if model_config.enable_thinking:
            call_kwargs["extra_body"] = {"enable_thinking": True}

        # Merge additional kwargs
        call_kwargs.update(kwargs)

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0

        stream = await self._openai_client.chat.completions.create(**call_kwargs)

        async for chunk in stream:
            if not chunk.choices and hasattr(chunk, "usage") and chunk.usage:
                # Final chunk with usage stats only
                input_tokens = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Collect reasoning content (thinking mode)
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)

            # Collect main content
            if delta.content:
                content_parts.append(delta.content)

            # Check usage on each chunk (some providers include it)
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = chunk.usage.prompt_tokens or input_tokens
                output_tokens = chunk.usage.completion_tokens or output_tokens

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)

        return LLMResponse(
            content=content,
            reasoning_content=reasoning,
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
        from dashscope import TextEmbedding

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

    def _estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
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
