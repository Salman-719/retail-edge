"""Post-deploy verification script for Job 6.

Checks:
  1. EEP /health returns {"status": "ok"}
  2. Prometheus /api/v1/targets — all targets health == "up"
  3. Grafana /api/health — database == "ok"

Exits 0 if all pass, 1 if any fail.

Usage
-----
    python scripts/ci_verify.py \
        --eep-url https://host:8000 \
        --prometheus-url http://host:9090 \
        --grafana-url https://host:3001

Environment variables
---------------------
    GRAFANA_USER      Grafana admin username. Default: admin
    GRAFANA_PASSWORD  Grafana admin password. Required for /api/health auth.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import requests

log = logging.getLogger("ci_verify")

GRAFANA_USER     = os.environ.get("GRAFANA_USER",     "admin")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "")

# Timeout for every HTTP check.
_TIMEOUT = 20


def check_eep(eep_url: str) -> bool:
    url = eep_url.rstrip("/") + "/health"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            log.info("EEP health OK")
            return True
        log.error("EEP /health returned unexpected body: %s", data)
        return False
    except Exception as exc:
        log.error("EEP health check failed: %s", exc)
        return False


def check_prometheus(prometheus_url: str) -> bool:
    url = prometheus_url.rstrip("/") + "/api/v1/targets"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        targets = resp.json()["data"]["activeTargets"]
        down = [t for t in targets if t["health"] != "up"]
        if down:
            for t in down:
                log.error(
                    "Prometheus target DOWN: job=%s url=%s error=%s",
                    t["labels"].get("job", "?"),
                    t.get("scrapeUrl", "?"),
                    t.get("lastError", "?"),
                )
            return False
        log.info("All %d Prometheus targets are UP.", len(targets))
        return True
    except Exception as exc:
        log.error("Prometheus targets check failed: %s", exc)
        return False


def check_grafana(grafana_url: str) -> bool:
    url = grafana_url.rstrip("/") + "/api/health"
    try:
        resp = requests.get(
            url,
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("database") == "ok":
            log.info("Grafana health OK (version=%s)", data.get("version", "?"))
            return True
        log.error("Grafana /api/health database not ok: %s", data)
        return False
    except Exception as exc:
        log.error("Grafana health check failed: %s", exc)
        return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Post-deploy verification")
    parser.add_argument("--eep-url",        required=True)
    parser.add_argument("--prometheus-url", required=True)
    parser.add_argument("--grafana-url",    required=True)
    args = parser.parse_args(argv)

    results = {
        "EEP":        check_eep(args.eep_url),
        "Prometheus": check_prometheus(args.prometheus_url),
        "Grafana":    check_grafana(args.grafana_url),
    }

    failures = [name for name, ok in results.items() if not ok]
    if failures:
        log.error("Verification FAILED: %s", ", ".join(failures))
        return 1

    log.info("All verification checks PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
