from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from typing import Any


class JsonEventProducer:
    async def start(self) -> None:
        return None

    async def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        return None


class LocalJsonlProducer(JsonEventProducer):
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        path = self.output_dir / f"{topic}.jsonl"
        envelope = {"topic": topic, "key": key, "value": value}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope, separators=(",", ":")) + "\n")


class KafkaJsonProducer(JsonEventProducer):
    def __init__(self, bootstrap_servers: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self._producer: Any = None

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer
        except Exception as exc:
            raise RuntimeError("aiokafka is required for EVENT_BUS_BACKEND=kafka") from exc
        kwargs: dict[str, Any] = {}
        security_protocol = os.getenv("VISION_KAFKA_SECURITY_PROTOCOL")
        if security_protocol:
            kwargs["security_protocol"] = security_protocol
        if security_protocol and "SSL" in security_protocol.upper():
            kwargs["ssl_context"] = ssl.create_default_context(cafile=os.getenv("VISION_KAFKA_CA_FILE") or None)
        sasl_mechanism = os.getenv("VISION_KAFKA_SASL_MECHANISM")
        sasl_username = os.getenv("VISION_KAFKA_SASL_USERNAME")
        sasl_password = os.getenv("VISION_KAFKA_SASL_PASSWORD")
        if sasl_mechanism:
            kwargs["sasl_mechanism"] = sasl_mechanism
        if sasl_username:
            kwargs["sasl_plain_username"] = sasl_username
        if sasl_password:
            kwargs["sasl_plain_password"] = sasl_password
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            key_serializer=lambda value: value.encode("utf-8"),
            **kwargs,
        )
        await self._producer.start()

    async def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Kafka producer was not started")
        await self._producer.send_and_wait(topic, key=key, value=value)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()


def create_event_producer() -> JsonEventProducer:
    backend = os.getenv("EVENT_BUS_BACKEND", "local").lower()
    if backend == "kafka":
        return KafkaJsonProducer(os.getenv("VISION_EVENT_BOOTSTRAP_SERVERS", "redpanda:9092"))
    return LocalJsonlProducer(os.getenv("IEP1_EVENT_LOG_DIR", "/app/runtime/events"))
