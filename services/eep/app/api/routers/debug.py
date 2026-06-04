import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.grpc_generated import agent_pb2
from app.grpc_server import registry

router = APIRouter(prefix="/api/debug", tags=["debug"])


class SendCommandRequest(BaseModel):
    store_id: str
    camera_id: str
    action: str
    rtsp_url: str = "rtsp://test/stream"
    target_fps: float = 5.0
    window_seconds: float = 60.0


@router.post("/agent/command")
async def send_agent_command(body: SendCommandRequest):
    if body.action == "start":
        msg = agent_pb2.ControlMessage(
            start_camera=agent_pb2.StartCamera(
                camera_id=body.camera_id,
                store_id=body.store_id,
                rtsp_url=body.rtsp_url,
                target_fps=body.target_fps,
                window_seconds=body.window_seconds,
                redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
                s3_config=agent_pb2.S3Config(
                    endpoint_url=os.environ.get("S3_ENDPOINT_URL", ""),
                    access_key=os.environ.get("S3_ACCESS_KEY", ""),
                    secret_key=os.environ.get("S3_SECRET_KEY", ""),
                    bucket=os.environ.get("S3_BUCKET", "retailvision"),
                ),
            )
        )
    elif body.action == "stop":
        msg = agent_pb2.ControlMessage(
            stop_camera=agent_pb2.StopCamera(
                camera_id=body.camera_id,
                store_id=body.store_id,
            )
        )
    else:
        raise HTTPException(status_code=400, detail="action must be start or stop")

    result = await registry.send_command(body.store_id, msg)
    if result == "disconnected":
        raise HTTPException(
            status_code=404,
            detail=f"No agent connected for store {body.store_id}",
        )
    if result == "queue_full":
        raise HTTPException(
            status_code=429,
            detail=f"Command queue full for store {body.store_id}",
        )
    return {"status": "sent", "action": body.action, "camera_id": body.camera_id}
