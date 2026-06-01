from __future__ import annotations

import json
import os
import ssl
from typing import Any, AsyncIterator


def _kafka_security_kwargs() -> dict[str, Any]:
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
    return kwargs


class KafkaJsonProducer:
    def __init__(self, bootstrap_servers: str | None = None) -> None:
        self.bootstrap_servers = bootstrap_servers or os.getenv("VISION_EVENT_BOOTSTRAP_SERVERS", "redpanda:9092")
        self._producer: Any = None

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer
        except Exception as exc:
            raise RuntimeError("aiokafka is required for Kafka event publishing") from exc
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            key_serializer=lambda value: value.encode("utf-8"),
            **_kafka_security_kwargs(),
        )
        await self._producer.start()

    async def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Kafka producer was not started")
        await self._producer.send_and_wait(topic, key=key, value=value)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()


class KafkaJsonConsumer:
    def __init__(self, topic: str, group_id: str, bootstrap_servers: str | None = None) -> None:
        self.topic = topic
        self.group_id = group_id
        self.bootstrap_servers = bootstrap_servers or os.getenv("VISION_EVENT_BOOTSTRAP_SERVERS", "redpanda:9092")
        self._consumer: Any = None

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer
        except Exception as exc:
            raise RuntimeError("aiokafka is required for Kafka event consumption") from exc
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset=os.getenv("VISION_CONSUMER_OFFSET_RESET", "latest"),
            enable_auto_commit=True,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
            key_deserializer=lambda raw: raw.decode("utf-8") if raw else None,
            **_kafka_security_kwargs(),
        )
        await self._consumer.start()

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._consumer is None:
            raise RuntimeError("Kafka consumer was not started")
        async for message in self._consumer:
            yield message.value

    async def stop(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
