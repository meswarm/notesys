"""Retry logic and output validation for LLM responses."""

import json
import re
from typing import Any, Callable, Optional

from loguru import logger


def validate_json_output(response_text: str) -> Optional[dict]:
    """Validate and parse JSON from LLM response.

    Attempts to extract JSON from the response, handling cases where
    the model wraps JSON in markdown code blocks.

    Args:
        response_text: Raw LLM response text.

    Returns:
        Parsed dictionary if valid JSON found, None otherwise.
    """
    text = response_text.strip()

    # Try direct JSON parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` code blocks
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object pattern
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def validate_markdown_images(response_text: str) -> bool:
    """Validate that response contains proper markdown image syntax.

    Args:
        response_text: LLM response with markdown images.

    Returns:
        True if all image references have non-empty alt text.
    """
    # Find all image references
    images = re.findall(r"!\[(.*?)\]\((.*?)\)", response_text)
    if not images:
        return True  # No images to validate

    # Check all have non-empty alt text
    for alt, path in images:
        if not alt.strip():
            return False
    return True


def build_format_retry_prompt(original_prompt: str, format_description: str) -> str:
    """Build a retry prompt that emphasizes output format requirements.

    Args:
        original_prompt: The original prompt that produced invalid output.
        format_description: Description of the expected format.

    Returns:
        Enhanced prompt with format emphasis.
    """
    return (
        f"{original_prompt}\n\n"
        f"⚠️ 重要：请严格按照以下格式输出，不要包含任何其他内容：\n"
        f"{format_description}"
    )
