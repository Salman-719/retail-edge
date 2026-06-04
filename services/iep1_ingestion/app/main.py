import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger = logging.getLogger(__name__)
    logger.info(
        "IEP1 daemon starting  redis=%s  control_sock=%s",
        os.environ.get("LOCAL_REDIS_URL", "redis://127.0.0.1:6379/0"),
        os.environ.get("IEP1_CONTROL_SOCK", "unix:///tmp/iep1-sockets/iep1_control.sock"),
    )

    from services.iep1_ingestion.app.daemon import run_daemon
    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
