import hmac
import logging
import os
from typing import Callable

import grpc
import grpc.aio

log = logging.getLogger(__name__)

# Loaded once at startup — KeyError if AGENT_SECRET not set, which is correct
# (EEP must not start without a shared secret).
_AGENT_SECRET: bytes = os.environ.get("AGENT_SECRET", "").encode("utf-8")


def _token_valid(provided: str) -> bool:
    if not _AGENT_SECRET:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), _AGENT_SECRET)


class AgentAuthInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(
        self,
        continuation: Callable,
        handler_call_details: grpc.HandlerCallDetails,
    ):
        metadata = dict(handler_call_details.invocation_metadata)
        token = metadata.get("x-agent-token", "")

        if not token:
            async def abort_missing(request, context: grpc.aio.ServicerContext):
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, "Missing x-agent-token"
                )
            return grpc.unary_unary_rpc_method_handler(abort_missing)

        if not _token_valid(token):
            log.warning("gRPC auth: invalid token rejected from peer")

            async def abort_invalid(request, context: grpc.aio.ServicerContext):
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, "Invalid agent token"
                )
            return grpc.unary_unary_rpc_method_handler(abort_invalid)

        return await continuation(handler_call_details)
