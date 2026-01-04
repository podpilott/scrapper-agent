"""SSE endpoint for real-time job streaming."""

import asyncio
import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.api.middleware.supabase_auth import AuthUser, verify_sse_token
from src.api.services.job_manager import job_manager
from src.utils.logger import get_logger

logger = get_logger("stream")

router = APIRouter()


async def event_generator(
    job_id: str,
    user_id: str,
    last_event_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a job.

    Yields events in SSE format:
    event: <type>
    id: <sequential_id>
    data: <json>

    Args:
        job_id: The job ID to stream events for.
        user_id: The authenticated user's ID.
        last_event_id: Last event ID received (for reconnection).

    Yields:
        SSE formatted event strings.
    """
    job = job_manager.get_job(job_id)
    if not job:
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': 'Job not found', 'recoverable': False})}\n\n"
        return

    if job.user_id != user_id and user_id != "dev-user":
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': 'Not authorized', 'recoverable': False})}\n\n"
        return

    event_id = 0

    # Send buffered events (for reconnection via Last-Event-ID)
    start_from = (last_event_id or -1) + 1
    for i, event in enumerate(job.event_buffer):
        if i >= start_from:
            event_id = i
            event_type = event.get("type", "message")
            yield f"event: {event_type}\nid: {event_id}\ndata: {json.dumps(event)}\n\n"

    # If job already completed, exit
    if job.status in ("completed", "failed", "cancelled"):
        return

    # Register for new events
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_event(event: dict[str, Any]) -> None:
        try:
            event_queue.put_nowait(event)
        except Exception:
            pass

    job_manager.register_callback(job_id, on_event)

    try:
        while True:
            try:
                # Wait for event with timeout (keep-alive every 15s)
                event = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                event_id += 1
                event_type = event.get("type", "message")
                yield f"event: {event_type}\nid: {event_id}\ndata: {json.dumps(event)}\n\n"

                # Exit on terminal events
                if event_type in ("complete", "error") and not event.get("recoverable"):
                    break

            except asyncio.TimeoutError:
                # Send keep-alive comment (SSE spec allows comments starting with :)
                yield ": keep-alive\n\n"

    finally:
        job_manager.unregister_callback(job_id, on_event)


@router.get("/jobs/{job_id}/stream")
async def stream_job(
    job_id: str,
    request: Request,
    auth_user: AuthUser = Depends(verify_sse_token),
) -> StreamingResponse:
    """Stream job events via Server-Sent Events (SSE).

    Connect to receive real-time updates:
    - status: Progress updates (step, current, total, message)
    - lead: New lead found
    - lead_update: Lead enriched with more data
    - error: Error occurred (check 'recoverable' field)
    - complete: Job finished (includes summary)

    Supports automatic reconnection via Last-Event-ID header.
    The browser's EventSource API handles reconnection automatically.

    Args:
        job_id: The job ID to stream.
        request: FastAPI request object.
        auth_user: Authenticated user from token.

    Returns:
        StreamingResponse with SSE content type.
    """
    # Parse Last-Event-ID for reconnection
    last_event_id = None
    last_event_header = request.headers.get("Last-Event-ID")
    if last_event_header:
        try:
            last_event_id = int(last_event_header)
        except ValueError:
            pass

    logger.info(
        "sse_stream_started",
        job_id=job_id,
        user_id=auth_user.user_id,
        last_event_id=last_event_id,
    )

    return StreamingResponse(
        event_generator(job_id, auth_user.user_id, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
