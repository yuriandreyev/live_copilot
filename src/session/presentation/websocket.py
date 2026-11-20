from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from copilot_contracts.events import ClientCommand, ServerEvent, client_command_adapter
from session.application.live_session import (
    CaptureRejected,
    ClientDisconnected,
    LiveSessionGateway,
)


def websocket_routes(gateway: LiveSessionGateway) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/sessions/{session_id}")
    async def capture(socket: WebSocket, session_id: UUID) -> None:
        await socket.accept()

        async def receive() -> ClientCommand | bytes:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                raise ClientDisconnected
            if message.get("bytes") is not None:
                return message["bytes"]
            try:
                return client_command_adapter.validate_json(message["text"])
            except ValidationError:
                raise CaptureRejected(
                    "invalid_command", "Send a valid versioned capture command."
                ) from None

        async def send(event: ServerEvent) -> None:
            try:
                await socket.send_text(event.model_dump_json())
            except (WebSocketDisconnect, OSError):
                raise ClientDisconnected from None

        close_code = await gateway.run(session_id, receive, send)
        if close_code is not None:
            try:
                await socket.close(code=close_code)
            except (WebSocketDisconnect, OSError):
                pass

    return router
