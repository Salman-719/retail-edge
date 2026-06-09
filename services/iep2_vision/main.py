"""IEP2 daemon entrypoint — env vars only, no CLI args (R2 M2-S4)."""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("iep2.main")

    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)

    try:
        from runtime import Settings, run_daemon
    except ImportError:
        from services.iep2_vision.runtime import Settings, run_daemon

    try:
        settings = Settings()
    except Exception as exc:
        log.error("Settings validation failed: %s", exc)
        sys.exit(1)

    # Start Prometheus metrics HTTP server before the pipeline loop so Prometheus
    # sees the target as UP from the moment the daemon is ready.
    metrics_port = int(os.getenv("IEP2_METRICS_PORT", "9201"))
    try:
        from metrics import start_metrics_server
    except ImportError:
        from services.iep2_vision.metrics import start_metrics_server
    start_metrics_server(metrics_port)
    log.info("Prometheus metrics server started on :%d", metrics_port)

    log.info(
        "IEP2 starting  camera=%s  store=%s  window_seconds=%.1f",
        settings.camera_id, settings.store_id, settings.window_seconds,
    )

    asyncio.run(run_daemon(settings))


if __name__ == "__main__":
    main()
