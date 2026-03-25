"""Data models for async task tracking."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskState(str, Enum):
    """Task execution states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskInfo(BaseModel):
    """Information about an async task."""

    task_id: str
    task_type: str  # "organize" or "query"
    state: TaskState = TaskState.PENDING
    current_step: str = ""
    progress: float = 0.0
    result: Optional[dict[str, Any]] = None
    error: str = ""
