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

    # Import through the PACKAGE path only, and never put this directory on
    # sys.path. Mixing `services.iep2_vision.metrics` with a top-level `metrics`
    # loads the same file as two distinct module objects, so every Counter is
    # registered twice and the process dies at import time with
    # "Duplicated timeseries in CollectorRegistry: iep2_frames_processed".
    # runtime.py already prefers relative imports, so this keeps one instance of
    # each sibling module.
    from services.iep2_vision.metrics import start_metrics_server
    from services.iep2_vision.runtime import Settings, run_daemon

    try:
        settings = Settings()
    except Exception as exc:
        log.error("Settings validation failed: %s", exc)
        sys.exit(1)

    # Start Prometheus metrics HTTP server before the pipeline loop so Prometheus
    # sees the target as UP from the moment the daemon is ready. Started exactly
    # once — this used to run twice, which also raced the port bind.
    metrics_port = int(os.environ.get("IEP2_METRICS_PORT", "9201"))
    start_metrics_server(metrics_port)
    log.info("Prometheus metrics server started on :%d", metrics_port)

    log.info(
        "IEP2 starting  camera=%s  store=%s  window_seconds=%.1f",
        settings.camera_id, settings.store_id, settings.window_seconds,
    )

    asyncio.run(run_daemon(settings))


if __name__ == "__main__":
    main()
