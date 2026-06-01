import asyncio
import os
import sys

from services.edge_agent.app.agent import run_agent


def main():
    grpc_url  = os.environ.get("EEP_GRPC_URL")
    store_id  = os.environ.get("STORE_ID")
    agent_ver = os.environ.get("AGENT_VERSION", "0.1.0")

    if not grpc_url or not store_id:
        print("ERROR: EEP_GRPC_URL and STORE_ID are required", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_agent(grpc_url, store_id, agent_ver))


if __name__ == "__main__":
    main()
