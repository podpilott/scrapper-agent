"""WebSocket connection handler for real-time streaming."""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.api.middleware.supabase_auth import verify_websocket_token
from src.api.services.job_manager import job_manager
from src.utils.logger import get_logger

logger = get_logger("websocket")

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections for job streaming."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        if job_id not in self._connections:
            self._connections[job_id] = []
        self._connections[job_id].append(websocket)
        logger.info("websocket_connected", job_id=job_id)

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if job_id in self._connections:
            try:
                self._connections[job_id].remove(websocket)
            except ValueError:
                pass
            if not self._connections[job_id]:
                del self._connections[job_id]
        logger.info("websocket_disconnected", job_id=job_id)

    async def send_message(self, job_id: str, message: dict[str, Any]) -> None:
        """Send message to all connections for a job."""
        if job_id in self._connections:
            disconnected = []
            for websocket in self._connections[job_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)

            # Clean up disconnected sockets
            for ws in disconnected:
                self.disconnect(job_id, ws)

    async def broadcast_event(self, job_id: str, event: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients for a job."""
        await self.send_message(job_id, event)


# Global connection manager
connection_manager = ConnectionManager()


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    job_id: str,
    token: str | None = Query(default=None),
):
    """WebSocket endpoint for job streaming.

    Connects to a job and receives real-time updates:
    - status: Progress updates
    - lead: New lead found
    - error: Error occurred
    - complete: Job completed
    """
    # Verify auth token
    auth_user = await verify_websocket_token(token)
    if not auth_user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    job = job_manager.get_job(job_id)
    if not job:
        await websocket.close(code=4004, reason="Job not found")
        return

    # Check ownership (allow dev-user to access all jobs)
    if job.user_id != auth_user.user_id and auth_user.user_id != "dev-user":
        await websocket.close(code=4003, reason="Not authorized to access this job")
        return

    await connection_manager.connect(job_id, websocket)

    # Send buffered events (for reconnection)
    for event in job.event_buffer:
        try:
            await websocket.send_json(event)
        except Exception:
            break

    # Register callback for new events
    event_queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict[str, Any]):
        try:
            event_queue.put_nowait(event)
        except Exception:
            pass

    job_manager.register_callback(job_id, on_event)

    try:
        # Listen for events and forward to WebSocket
        while True:
            try:
                # Wait for event with timeout to check connection
                event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                await websocket.send_json(event)

                # Check if job is complete
                if event.get("type") in ("complete", "error"):
                    if not event.get("recoverable", True):
                        break
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", job_id=job_id)
    except Exception as e:
        logger.warning("websocket_error", job_id=job_id, error=str(e))
    finally:
        job_manager.unregister_callback(job_id, on_event)
        connection_manager.disconnect(job_id, websocket)
