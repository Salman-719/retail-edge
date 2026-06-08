"""Cloud-side IEP5 (end-of-shift analytics) job launcher.

IEP5 runs once per (store, shift_date) and exits. EEP launches it after the
shift-closing transaction (see shift_closer.py).
  run_iep5_job(store_id, shift_date) — k8s batch/v1 Job [TODO] or Docker run

k8s does retries via backoffLimit in production. The Docker path is single-shot
(no auto-retry) — fine for local/dev. Falls back to Docker when k8s is
unavailable; locally `_apps_v1` is None so the Docker path is used.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_NAMESPACE      = os.environ.get("K8S_NAMESPACE",   "retailvision")
_IEP5_IMAGE     = os.environ.get("IEP5_IMAGE",      "retail-edge-iep5_analytics:latest")
_KUBECONFIG     = os.environ.get("KUBECONFIG",      "")
_DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK",  "retail-edge_default")

_WINDOW_SECONDS          = os.environ.get("WINDOW_SECONDS",          "60")
_DATABASE_URL_SERVER     = os.environ.get("DATABASE_URL_SERVER",     "")
_HEATMAP_CELL_SIZE_M     = os.environ.get("HEATMAP_CELL_SIZE_M",     "0.5")
_PASSTHROUGH_DWELL_MS    = os.environ.get("PASSTHROUGH_DWELL_MS",    "30000")
_DEAD_PERIOD_THRESHOLD   = os.environ.get("DEAD_PERIOD_THRESHOLD",   "3")
_DEAD_PERIOD_DURATION_MS = os.environ.get("DEAD_PERIOD_DURATION_MS", "1800000")

_batch_v1 = None
_docker_client = None


def init_k8s_clients() -> None:
    global _batch_v1, _docker_client
    try:
        from kubernetes import client as k8s, config as k8s_config  # type: ignore[import-untyped]
        try:
            k8s_config.load_incluster_config()
            log.info("iep5_manager: using in-cluster k8s config")
        except k8s_config.ConfigException:
            kubeconfig = _KUBECONFIG or None
            try:
                k8s_config.load_kube_config(config_file=kubeconfig)
                log.info("iep5_manager: using kubeconfig %s", kubeconfig or "~/.kube/config")
            except Exception as exc:
                log.warning("iep5_manager: k8s unavailable (%s) — trying Docker fallback", exc)
                _init_docker()
                return
        _batch_v1 = k8s.BatchV1Api()
    except ImportError:
        log.warning("iep5_manager: 'kubernetes' package not installed — trying Docker fallback")
        _init_docker()


def _init_docker() -> None:
    global _docker_client
    try:
        import docker  # type: ignore[import-untyped]
        _docker_client = docker.from_env()
        log.info("iep5_manager: Docker fallback active (production-local mode)")
    except Exception as exc:
        log.warning("iep5_manager: Docker also unavailable — IEP5 will not run (%s)", exc)


def _job_name(store_id: str, shift_date: str) -> str:
    return "iep5-" + store_id.replace("-", "")[:16] + "-" + shift_date


def _env(store_id: str, shift_date: str) -> dict[str, str]:
    return {
        "STORE_ID":                store_id,
        "SHIFT_DATE":              shift_date,
        "DATABASE_URL_SERVER":     _DATABASE_URL_SERVER,
        "WINDOW_SECONDS":          _WINDOW_SECONDS,
        "HEATMAP_CELL_SIZE_M":     _HEATMAP_CELL_SIZE_M,
        "PASSTHROUGH_DWELL_MS":    _PASSTHROUGH_DWELL_MS,
        "DEAD_PERIOD_THRESHOLD":   _DEAD_PERIOD_THRESHOLD,
        "DEAD_PERIOD_DURATION_MS": _DEAD_PERIOD_DURATION_MS,
    }


def run_iep5_job(store_id: str, shift_date: str) -> str | None:
    """Launch the IEP5 job for (store_id, shift_date). Returns the job/container name."""
    if _batch_v1 is not None:
        return _run_iep5_k8s(store_id, shift_date)
    return _run_iep5_docker(store_id, shift_date)


def _run_iep5_k8s(store_id: str, shift_date: str) -> str | None:
    # TODO(k8s deploy): create a batch/v1 Job (backoffLimit=3,
    # ttlSecondsAfterFinished=86400, restartPolicy=Never, env from _env(),
    # DATABASE_URL_SERVER from the retailvision-secrets secret). Stubbed.
    log.warning(
        "iep5_manager: k8s Job path not implemented yet — TODO (store=%s date=%s)",
        store_id, shift_date,
    )
    return None


def _run_iep5_docker(store_id: str, shift_date: str) -> str | None:
    if _docker_client is None:
        log.debug("iep5_manager.run_iep5_job: no backend available, skipping (store=%s)", store_id)
        return None
    import docker.errors  # type: ignore[import-untyped]

    name = _job_name(store_id, shift_date)
    # Remove any prior run with the same name so a re-trigger is idempotent.
    try:
        _docker_client.containers.get(name).remove(force=True)
    except docker.errors.NotFound:
        pass

    _docker_client.containers.run(
        image=_IEP5_IMAGE,
        name=name,
        environment=_env(store_id, shift_date),
        network=_DOCKER_NETWORK,
        detach=True,                       # single-shot; container exits on completion
        restart_policy={"Name": "no"},
        labels={"component": "iep5", "store-id": store_id, "shift-date": shift_date,
                "managed-by": "eep"},
    )
    log.info("iep5_manager: launched IEP5 job %s (store=%s date=%s)", name, store_id, shift_date)
    return name
