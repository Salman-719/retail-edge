from __future__ import annotations

import os
import uuid
from typing import Any


class EepClient:
    def __init__(self, base_url: str | None = None, internal_token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("EEP_BASE_URL", "http://eep:8000")).rstrip("/")
        self.internal_token = internal_token if internal_token is not None else os.getenv("VISION_INTERNAL_TOKEN", "")

    def _headers(self) -> dict[str, str]:
        if not self.internal_token:
            return {}
        return {"x-vision-internal-token": self.internal_token}

    async def load_topology(self, store_id: uuid.UUID) -> dict[str, Any]:
        try:
            import httpx
        except Exception as exc:
            raise RuntimeError("httpx is required for EEP topology loading") from exc

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/api/internal/vision/topology",
                params={"store_id": str(store_id)},
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def post_camera_health(self, payload: dict[str, Any]) -> None:
        try:
            import httpx
        except Exception:
            return

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{self.base_url}/api/internal/vision/camera-health",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
