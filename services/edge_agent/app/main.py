import asyncio
import logging
import os
import sys

from services.edge_agent.app.agent import run_agent

_REQUIRED_VARS = ["EEP_GRPC_URL", "STORE_ID", "DATABASE_URL_SERVER", "SERVER_REDIS_URL"]


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        print(f"ERROR: required env vars not set: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    grpc_url  = os.environ["EEP_GRPC_URL"]
    store_id  = os.environ["STORE_ID"]
    agent_ver = os.environ.get("AGENT_VERSION", "0.1.0")

    asyncio.run(run_agent(grpc_url, store_id, agent_ver))


if __name__ == "__main__":
    main()
