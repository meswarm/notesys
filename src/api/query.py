"""Query Agent API endpoints."""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.events import SSEEvent

router = APIRouter(prefix="/api", tags=["query"])

# In-memory task store (for SSE event streaming)
_tasks: dict[str, dict] = {}


class QueryRequest(BaseModel):
    """Request body for note query."""

    query: str
    top_k: int = 10
    enable_rewrite: Optional[bool] = None      # None = 使用配置文件默认值
    enable_synthesis: Optional[bool] = None    # None = 使用配置文件默认值


class QueryResponse(BaseModel):
    """Response with task ID for SSE subscription."""

    task_id: str
    message: str = "查询任务已创建，请订阅 SSE 获取进度"


def get_pipeline():
    """Get querier pipeline from app state. Set by main.py."""
    from src.main import app
    return app.state.querier_pipeline


@router.post("/query", response_model=QueryResponse)
async def query_notes(request: QueryRequest):
    """Submit a query to search notes.

    Creates an async task and returns a task_id. Use the SSE endpoint
    to monitor progress and get results.
    """
    task_id = str(uuid.uuid4())

    event_queue: asyncio.Queue[Optional[SSEEvent]] = asyncio.Queue()
    _tasks[task_id] = {"queue": event_queue, "done": False}

    async def event_callback(event: SSEEvent):
        await event_queue.put(event)

    async def run_pipeline():
        try:
            pipeline = get_pipeline()
            await pipeline.run(
                user_query=request.query,
                top_k=request.top_k,
                enable_rewrite=request.enable_rewrite,
                enable_synthesis=request.enable_synthesis,
                event_callback=event_callback,
            )
        finally:
            await event_queue.put(None)
            _tasks[task_id]["done"] = True

    asyncio.create_task(run_pipeline())

    return QueryResponse(task_id=task_id)


@router.get("/query/{task_id}/stream")
async def query_stream(task_id: str):
    """SSE stream for query progress and results."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    event_queue = _tasks[task_id]["queue"]

    async def event_generator():
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield event.format()

        if task_id in _tasks:
            del _tasks[task_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
