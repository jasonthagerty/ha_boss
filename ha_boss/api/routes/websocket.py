"""WebSocket endpoints for real-time dashboard updates."""

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ha_boss.api.websocket_manager import get_websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    instance_id: str = Query("default", description="Instance identifier"),
) -> None:
    """WebSocket endpoint for real-time dashboard updates.

    Clients connect to this endpoint to receive real-time updates for entity states,
    health status, healing actions, and instance connection changes.

    Args:
        websocket: WebSocket connection
        instance_id: Instance to subscribe to (default: "default")

    Message Types Sent to Client:
        - connected: Initial connection confirmation
        - entity_state_changed: Entity state update
        - health_status: Health status update
        - healing_action: Healing action notification
        - instance_connection: Instance connection status change

    Message Types Received from Client:
        - subscribe: Update subscriptions
        - ping: Heartbeat (responds with pong)

    Example Client Messages:
        {"type": "subscribe", "subscriptions": ["status", "entities", "health"]}
        {"type": "ping"}
    """
    manager = get_websocket_manager()

    try:
        # Connect and subscribe to instance
        await manager.connect(websocket, instance_id)

        # Message loop
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                message_type = message.get("type")

                if message_type == "ping":
                    # Respond to heartbeat
                    await websocket.send_json(
                        {"type": "pong", "timestamp": message.get("timestamp")}
                    )

                elif message_type == "subscribe":
                    # Update subscriptions
                    subscriptions = set(message.get("subscriptions", []))
                    await manager.update_subscription(websocket, subscriptions)
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "subscriptions": list(subscriptions),
                        }
                    )

                elif message_type == "switch_instance":
                    # Switch to different instance
                    new_instance_id = message.get("instance_id", "default")

                    # Disconnect from current instance
                    await manager.disconnect(websocket)

                    # Connect to new instance
                    await manager.connect(websocket, new_instance_id)

                else:
                    logger.warning(f"Unknown message type from {id(websocket)}: {message_type}")

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from {id(websocket)}: {data}")
            except Exception as e:
                logger.error(f"Error processing message from {id(websocket)}: {e}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket client {id(websocket)} disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error for {id(websocket)}: {e}", exc_info=True)
    finally:
        # Cleanup on disconnect
        await manager.disconnect(websocket)
