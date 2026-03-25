"""SSE (Server-Sent Events) event definitions."""

import json
from datetime import datetime
from typing import Any, Optional


class EventType:
    """SSE event type constants."""

    PROGRESS = "progress"   # 进度更新
    STATUS = "status"       # 状态变更
    RESULT = "result"       # 最终结果
    ERROR = "error"         # 错误信息


class SSEEvent:
    """Represents a single SSE event."""

    def __init__(
        self,
        event_type: str,
        data: dict[str, Any],
        event_id: Optional[str] = None,
    ):
        self.event_type = event_type
        self.data = data
        self.data["timestamp"] = datetime.now().isoformat()
        self.event_id = event_id

    def format(self) -> str:
        """Format as SSE text.

        Returns:
            SSE formatted string: 'event: ...\ndata: ...\n\n'
        """
        lines = []
        if self.event_id:
            lines.append(f"id: {self.event_id}")
        lines.append(f"event: {self.event_type}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False)}")
        lines.append("")  # Trailing newline
        lines.append("")  # Double newline to end event
        return "\n".join(lines)


def progress_event(step: str, progress: float, message: str = "") -> SSEEvent:
    """Create a progress event.

    Args:
        step: Current pipeline step name.
        progress: Progress percentage (0.0 to 1.0).
        message: Optional human-readable message.
    """
    return SSEEvent(
        event_type=EventType.PROGRESS,
        data={"step": step, "progress": progress, "message": message},
    )


def status_event(status: str, message: str) -> SSEEvent:
    """Create a status event.

    Args:
        status: Status string (e.g., 'processing', 'waiting').
        message: Human-readable status message.
    """
    return SSEEvent(
        event_type=EventType.STATUS,
        data={"status": status, "message": message},
    )


def result_event(data: dict[str, Any]) -> SSEEvent:
    """Create a result event.

    Args:
        data: Result data dictionary.
    """
    return SSEEvent(event_type=EventType.RESULT, data=data)


def error_event(error: str, retry: bool = False, step: str = "") -> SSEEvent:
    """Create an error event.

    Args:
        error: Error message.
        retry: Whether the system will retry.
        step: Pipeline step where error occurred.
    """
    return SSEEvent(
        event_type=EventType.ERROR,
        data={"error": error, "retry": retry, "step": step},
    )
