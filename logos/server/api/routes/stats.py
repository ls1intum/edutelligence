from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio

from server.core.scheduler import get_scheduler_stats

router = APIRouter()

class StatsConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

stats_manager = StatsConnectionManager()

@router.websocket("/ws")
async def stats_websocket(websocket: WebSocket):
    await stats_manager.connect(websocket)
    try:
        while True:
            stats = get_scheduler_stats()
            await websocket.send_json(stats)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        stats_manager.disconnect(websocket)
    except Exception:
        stats_manager.disconnect(websocket)