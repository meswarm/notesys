"""Organize Agent API endpoints."""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.events import SSEEvent

router = APIRouter(prefix="/api", tags=["organize"])

# In-memory task store (for SSE event streaming)
_tasks: dict[str, dict] = {}


class OrganizeRequest(BaseModel):
    """Request body for note organization."""

    markdown_content: str
    notes_root_path: Optional[str] = None            # 笔记存储根目录（不填用服务端默认值）
    images_dir: Optional[str] = None                # 图片目录（不填用 notes_root_path）
    enable_image_semantic: Optional[bool] = None    # None = 使用配置文件默认值
    enable_note_format: Optional[bool] = None       # None = 使用配置文件默认值
    enable_classify_and_save: Optional[bool] = None  # None = 使用配置文件默认值
    add_date_stamp: Optional[bool] = True            # 是否在保存前加日期戳（YYYY-MM-DD）


class OrganizeResponse(BaseModel):
    """Response with task ID for SSE subscription."""

    task_id: str
    message: str = "任务已创建，请订阅 SSE 获取进度"


def get_pipeline():
    """Get organizer pipeline from app state. Set by main.py."""
    from src.main import app
    return app.state.organizer_pipeline


@router.post("/organize", response_model=OrganizeResponse)
async def organize_note(request: OrganizeRequest):
    """Submit a note for organization.

    Creates an async task and returns a task_id. Use the SSE endpoint
    to monitor progress and get results.
    """
    task_id = str(uuid.uuid4())

    # Create event queue for SSE
    event_queue: asyncio.Queue[Optional[SSEEvent]] = asyncio.Queue()
    _tasks[task_id] = {"queue": event_queue, "done": False}

    async def event_callback(event: SSEEvent):
        await event_queue.put(event)

    async def run_pipeline():
        try:
            pipeline = get_pipeline()
            await pipeline.run(
                raw_markdown=request.markdown_content,
                notes_root_path=request.notes_root_path,
                images_dir=request.images_dir,
                enable_image_semantic=request.enable_image_semantic,
                enable_note_format=request.enable_note_format,
                enable_classify_and_save=request.enable_classify_and_save,
                add_date_stamp=request.add_date_stamp,
                event_callback=event_callback,
            )
        finally:
            await event_queue.put(None)  # Signal end of stream
            _tasks[task_id]["done"] = True

    # Start pipeline in background
    asyncio.create_task(run_pipeline())

    return OrganizeResponse(task_id=task_id)


@router.get("/organize/{task_id}/stream")
async def organize_stream(task_id: str):
    """SSE stream for organization progress and results."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    event_queue = _tasks[task_id]["queue"]

    async def event_generator():
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield event.format()

        # Cleanup
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
