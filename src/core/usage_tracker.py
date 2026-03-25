"""Token usage tracking with JSONL persistence."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Record of a single LLM API call's token consumption."""

    timestamp: str
    model: str
    step: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0


class UsageTracker:
    """Tracks and persists token usage to JSONL files.

    Usage data is stored in daily JSONL files under the data/usage/ directory.
    Each line is a JSON object representing one API call.
    """

    def __init__(self, usage_dir: str = "data/usage"):
        self._usage_dir = Path(usage_dir)
        self._usage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory buffer for current task summary
        self._current_task_usages: list[TokenUsage] = []

    def _get_file_path(self) -> Path:
        """Get today's JSONL file path."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self._usage_dir / f"{today}.jsonl"

    async def record(self, usage: TokenUsage) -> None:
        """Record a single token usage entry.

        Appends to daily JSONL file and in-memory buffer.
        """
        self._current_task_usages.append(usage)

        file_path = self._get_file_path()
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(usage.model_dump_json() + "\n")

    def reset_task_summary(self) -> None:
        """Reset the in-memory task usage buffer."""
        self._current_task_usages.clear()

    def get_task_summary(self) -> dict:
        """Get a summary of token usage for the current task.

        Returns:
            Dictionary with total_tokens, total_cost, and per-step breakdown.
        """
        if not self._current_task_usages:
            return {"total_tokens": 0, "total_cost": 0.0, "breakdown": []}

        total_tokens = sum(u.total_tokens for u in self._current_task_usages)
        total_cost = sum(u.cost for u in self._current_task_usages)

        breakdown = []
        for u in self._current_task_usages:
            breakdown.append({
                "step": u.step,
                "model": u.model,
                "tokens": u.total_tokens,
                "cost": u.cost,
                "latency_ms": u.latency_ms,
            })

        return {
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 6),
            "breakdown": breakdown,
        }
