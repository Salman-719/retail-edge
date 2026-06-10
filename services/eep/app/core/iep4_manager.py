"""Cloud-side IEP4 (alert daemon) lifecycle manager.

Mirrors iep3_manager: one long-running IEP4 process per store.
  apply_iep4(store_id)  — create-or-run (k8s StatefulSet [TODO] or Docker container)
  delete_iep4(store_id) — idempotent delete

When k8s is unavailable (production-local / DEBUG_MODE), falls back to Docker.
The k8s StatefulSet path is a marked TODO stub for now — locally `_apps_v1` is
None so the Docker path is used.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_NAMESPACE      = os.environ.get("K8S_NAMESPACE",   "retailvision")
_IEP4_IMAGE     = os.environ.get("IEP4_IMAGE",      "retail-edge-iep4_alerts:latest")
_KUBECONFIG     = os.environ.get("KUBECONFIG",      "")
_DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK",  "retail-edge_default")

_WINDOW_SECONDS        = os.environ.get("WINDOW_SECONDS",        "60")
_DATABASE_URL_SERVER   = os.environ.get("DATABASE_URL_SERVER",   "")
_EVALUATION_BATCHES    = os.environ.get("EVALUATION_BATCHES",    "5")
_MAX_LOOKBACK_BATCHES  = os.environ.get("MAX_LOOKBACK_BATCHES",  "60")
_CATCHUP_BATCH_SIZE    = os.environ.get("CATCHUP_BATCH_SIZE",    "1")
# Production manager runs in production mode (email enabled when SMTP is set).
_ENVIRONMENT  = os.environ.get("ENVIRONMENT", "production")
_SMTP_HOST    = os.environ.get("SMTP_HOST",     "")
_SMTP_PORT    = os.environ.get("SMTP_PORT",     "587")
_SMTP_USER    = os.environ.get("SMTP_USER",     "")
_SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
_SMTP_FROM    = os.environ.get("SMTP_FROM",     "")

_apps_v1 = None
_core_v1 = None
_docker_client = None


def init_k8s_clients() -> None:
    global _apps_v1, _core_v1, _docker_client
    try:
        from kubernetes import client as k8s, config as k8s_config  # type: ignore[import-untyped]
        try:
            k8s_config.load_incluster_config()
            log.info("iep4_manager: using in-cluster k8s config")
        except k8s_config.ConfigException:
            kubeconfig = _KUBECONFIG or None
            try:
                k8s_config.load_kube_config(config_file=kubeconfig)
                log.info("iep4_manager: using kubeconfig %s", kubeconfig or "~/.kube/config")
            except Exception as exc:
                log.warning("iep4_manager: k8s unavailable (%s) — trying Docker fallback", exc)
                _init_docker()
                return
        _apps_v1 = k8s.AppsV1Api()
        _core_v1 = k8s.CoreV1Api()
    except ImportError:
        log.warning("iep4_manager: 'kubernetes' package not installed — trying Docker fallback")
        _init_docker()


def _init_docker() -> None:
    global _docker_client
    try:
        import docker  # type: ignore[import-untyped]
        _docker_client = docker.from_env()
        log.info("iep4_manager: Docker fallback active (production-local mode)")
    except Exception as exc:
        log.warning("iep4_manager: Docker also unavailable — IEP4 will not be managed (%s)", exc)


def _ss_name(store_id: str) -> str:
    # Match Helm/iep3 naming: strip dashes, truncate to 16 chars.
    return "iep4-" + store_id.replace("-", "")[:16]


def _container_name(store_id: str) -> str:
    return "iep4-prod-" + store_id.replace("-", "")[:16]


def _env(store_id: str) -> dict[str, str]:
    return {
        "STORE_ID":             store_id,
        "DATABASE_URL_SERVER":  _DATABASE_URL_SERVER,
        "WINDOW_SECONDS":       _WINDOW_SECONDS,
        "EVALUATION_BATCHES":   _EVALUATION_BATCHES,
        "MAX_LOOKBACK_BATCHES": _MAX_LOOKBACK_BATCHES,
        "CATCHUP_BATCH_SIZE":   _CATCHUP_BATCH_SIZE,
        "ENVIRONMENT":          _ENVIRONMENT,
        "SMTP_HOST":            _SMTP_HOST,
        "SMTP_PORT":            _SMTP_PORT,
        "SMTP_USER":            _SMTP_USER,
        "SMTP_PASSWORD":        _SMTP_PASSWORD,
        "SMTP_FROM":            _SMTP_FROM,
    }


def apply_iep4(store_id: str) -> None:
    """Create-or-run the IEP4 alert daemon for store_id (idempotent)."""
    if _apps_v1 is not None:
        _apply_iep4_k8s(store_id)
        return
    _apply_iep4_docker(store_id)


def _apply_iep4_k8s(store_id: str) -> None:
    """Create-or-patch the IEP4 alert-daemon StatefulSet for store_id.

    Mirrors iep3_manager.apply_iep3 but without a headless Service — IEP4 has no
    inbound port (it polls Postgres and sends SMTP). replicas=1, one per store.
    """
    from kubernetes import client as k8s  # type: ignore[import-untyped]
    from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

    name   = _ss_name(store_id)
    labels = {"app": "iep4", "store-id": store_id}

    # Env from _env() — values are already resolved in the EEP process (DB URL
    # and SMTP password come from EEP's own secret-backed env). IEP4 needs no Redis.
    env = [k8s.V1EnvVar(name=k, value=v) for k, v in _env(store_id).items()]

    ss = k8s.V1StatefulSet(
        metadata=k8s.V1ObjectMeta(name=name, namespace=_NAMESPACE, labels=labels),
        spec=k8s.V1StatefulSetSpec(
            replicas=1,
            service_name=name,
            selector=k8s.V1LabelSelector(match_labels=labels),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels=labels),
                spec=k8s.V1PodSpec(
                    service_account_name="iep4",
                    containers=[
                        k8s.V1Container(
                            name="iep4",
                            image=_IEP4_IMAGE,
                            env=env,
                            resources=k8s.V1ResourceRequirements(
                                requests={"cpu": "100m", "memory": "192Mi"},
                                limits={"cpu": "500m", "memory": "512Mi"},
                            ),
                            liveness_probe=k8s.V1Probe(
                                _exec=k8s.V1ExecAction(
                                    command=["python", "-c", "import sys; sys.exit(0)"]
                                ),
                                initial_delay_seconds=30,
                                period_seconds=30,
                                failure_threshold=3,
                            ),
                        )
                    ],
                ),
            ),
        ),
    )

    try:
        _apps_v1.read_namespaced_stateful_set(name, _NAMESPACE)
        _apps_v1.patch_namespaced_stateful_set(name, _NAMESPACE, ss)
        log.info("iep4_manager: patched StatefulSet %s (store=%s)", name, store_id)
    except ApiException as exc:
        if exc.status == 404:
            _apps_v1.create_namespaced_stateful_set(_NAMESPACE, ss)
            log.info("iep4_manager: created StatefulSet %s (store=%s)", name, store_id)
        else:
            raise


def _apply_iep4_docker(store_id: str) -> None:
    if _docker_client is None:
        log.debug("iep4_manager.apply_iep4: no backend available, skipping (store=%s)", store_id)
        return
    import docker.errors  # type: ignore[import-untyped]

    name = _container_name(store_id)
    try:
        existing = _docker_client.containers.get(name)
        if existing.status == "running":
            log.debug("iep4_manager: IEP4 container %s already running (store=%s)", name, store_id)
            return
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass

    _docker_client.containers.run(
        image=_IEP4_IMAGE,
        name=name,
        environment=_env(store_id),
        network=_DOCKER_NETWORK,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
        labels={"component": "iep4", "store-id": store_id, "managed-by": "eep"},
    )
    log.info("iep4_manager: started Docker container %s (store=%s)", name, store_id)


def delete_iep4(store_id: str) -> None:
    """Idempotent delete of the IEP4 daemon for store_id."""
    if _apps_v1 is not None:
        from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]
        name = _ss_name(store_id)
        try:
            _apps_v1.delete_namespaced_stateful_set(name, _NAMESPACE)
            log.info("iep4_manager: deleted StatefulSet %s (store=%s)", name, store_id)
        except ApiException as exc:
            if exc.status != 404:
                raise
        return
    if _docker_client is None:
        return
    import docker.errors  # type: ignore[import-untyped]
    name = _container_name(store_id)
    try:
        _docker_client.containers.get(name).remove(force=True)
        log.info("iep4_manager: removed Docker container %s (store=%s)", name, store_id)
    except docker.errors.NotFound:
        pass
