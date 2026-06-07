"""Cloud-side IEP3 lifecycle manager.

EEP owns the IEP3 lifecycle:
  apply_iep3(store_id)  — create-or-patch StatefulSet + headless Service (k8s)
                          or start a Docker container (production-local fallback)
  delete_iep3(store_id) — idempotent delete

Mirrors services/edge_agent/app/k8s_manager.py (which manages IEP2 on the edge).
When k8s is unavailable (production-local / DEBUG_MODE), falls back to Docker.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_NAMESPACE     = os.environ.get("K8S_NAMESPACE",   "retailvision")
_IEP3_IMAGE    = os.environ.get("IEP3_IMAGE",      "retailvision-iep3:latest")
_KUBECONFIG    = os.environ.get("KUBECONFIG",      "")
_DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "retail-edge_default")
_SERVER_REDIS_URL = os.environ.get("SERVER_REDIS_URL", "")

_WINDOW_SECONDS                   = os.environ.get("WINDOW_SECONDS",                   "60")
_DATABASE_URL_SERVER               = os.environ.get("DATABASE_URL_SERVER",               "")
_REID_THRESHOLD                   = os.environ.get("REID_THRESHOLD",                   "0.75")
_GRACE_SECONDS                    = os.environ.get("GRACE_SECONDS",                    "300.0")
_MAX_SPEED_MPS                    = os.environ.get("MAX_SPEED_MPS",                    "1.5")
_POSITION_WEIGHT_AREA             = os.environ.get("POSITION_WEIGHT_AREA",             "0.7")
_POSITION_WEIGHT_CONF             = os.environ.get("POSITION_WEIGHT_CONF",             "0.3")
_ORPHAN_SWEEP_INTERVAL_BATCHES    = os.environ.get("ORPHAN_SWEEP_INTERVAL_BATCHES",    "50")
_EXPECTED_CAMERAS_REFRESH_BATCHES = os.environ.get("EXPECTED_CAMERAS_REFRESH_BATCHES", "10")

_apps_v1 = None
_core_v1 = None
_docker_client = None


def init_k8s_clients() -> None:
    global _apps_v1, _core_v1, _docker_client
    try:
        from kubernetes import client as k8s, config as k8s_config  # type: ignore[import-untyped]
        try:
            k8s_config.load_incluster_config()
            log.info("iep3_manager: using in-cluster k8s config")
        except k8s_config.ConfigException:
            kubeconfig = _KUBECONFIG or None
            try:
                k8s_config.load_kube_config(config_file=kubeconfig)
                log.info("iep3_manager: using kubeconfig %s", kubeconfig or "~/.kube/config")
            except Exception as exc:
                log.warning(
                    "iep3_manager: k8s unavailable (%s) — trying Docker fallback", exc
                )
                _init_docker()
                return
        _apps_v1 = k8s.AppsV1Api()
        _core_v1 = k8s.CoreV1Api()
    except ImportError:
        log.warning("iep3_manager: 'kubernetes' package not installed — trying Docker fallback")
        _init_docker()


def _init_docker() -> None:
    global _docker_client
    try:
        import docker  # type: ignore[import-untyped]
        _docker_client = docker.from_env()
        log.info("iep3_manager: Docker fallback active (production-local mode)")
    except Exception as exc:
        log.warning("iep3_manager: Docker also unavailable — IEP3 will not be managed (%s)", exc)


def _ss_name(store_id: str) -> str:
    # Match Helm naming: strip dashes, truncate to 16 chars.
    return "iep3-" + store_id.replace("-", "")[:16]


def _container_name(store_id: str) -> str:
    return "iep3-prod-" + store_id.replace("-", "")[:16]


def apply_iep3(store_id: str) -> None:
    """Create-or-patch IEP3 StatefulSet + headless Service for store_id.

    Falls back to a Docker container when k8s is unavailable (production-local).
    """
    if _apps_v1 is None:
        _apply_iep3_docker(store_id)
        return

    from kubernetes import client as k8s  # type: ignore[import-untyped]
    from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

    name   = _ss_name(store_id)
    labels = {"app": "iep3", "store-id": store_id}

    # ── Headless Service (required by StatefulSet serviceName) ─────────────
    svc = k8s.V1Service(
        metadata=k8s.V1ObjectMeta(name=name, namespace=_NAMESPACE, labels=labels),
        spec=k8s.V1ServiceSpec(cluster_ip="None", selector=labels),
    )
    try:
        _core_v1.read_namespaced_service(name, _NAMESPACE)
        _core_v1.patch_namespaced_service(name, _NAMESPACE, svc)
    except ApiException as exc:
        if exc.status == 404:
            _core_v1.create_namespaced_service(_NAMESPACE, svc)
        else:
            raise

    # ── StatefulSet ────────────────────────────────────────────────────────
    env = [
        k8s.V1EnvVar(name="STORE_ID",                         value=store_id),
        k8s.V1EnvVar(name="WINDOW_SECONDS",                   value=_WINDOW_SECONDS),
        k8s.V1EnvVar(name="DATABASE_URL_SERVER",              value=_DATABASE_URL_SERVER),
        k8s.V1EnvVar(name="REID_THRESHOLD",                   value=_REID_THRESHOLD),
        k8s.V1EnvVar(name="GRACE_SECONDS",                    value=_GRACE_SECONDS),
        k8s.V1EnvVar(name="MAX_SPEED_MPS",                    value=_MAX_SPEED_MPS),
        k8s.V1EnvVar(name="POSITION_WEIGHT_AREA",             value=_POSITION_WEIGHT_AREA),
        k8s.V1EnvVar(name="POSITION_WEIGHT_CONF",             value=_POSITION_WEIGHT_CONF),
        k8s.V1EnvVar(name="ORPHAN_SWEEP_INTERVAL_BATCHES",    value=_ORPHAN_SWEEP_INTERVAL_BATCHES),
        k8s.V1EnvVar(name="EXPECTED_CAMERAS_REFRESH_BATCHES", value=_EXPECTED_CAMERAS_REFRESH_BATCHES),
        # SERVER_REDIS_URL pulled from k8s secret — matches Helm template.
        k8s.V1EnvVar(
            name="SERVER_REDIS_URL",
            value_from=k8s.V1EnvVarSource(
                secret_key_ref=k8s.V1SecretKeySelector(
                    name="retailvision-secrets",
                    key="redis-url",
                )
            ),
        ),
    ]

    ss = k8s.V1StatefulSet(
        metadata=k8s.V1ObjectMeta(name=name, namespace=_NAMESPACE, labels=labels),
        spec=k8s.V1StatefulSetSpec(
            replicas=1,
            service_name=name,
            selector=k8s.V1LabelSelector(match_labels=labels),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels=labels),
                spec=k8s.V1PodSpec(
                    service_account_name="iep3",
                    containers=[
                        k8s.V1Container(
                            name="iep3",
                            image=_IEP3_IMAGE,
                            env=env,
                            resources=k8s.V1ResourceRequirements(
                                requests={"cpu": "200m", "memory": "256Mi"},
                                limits={"cpu": "1000m", "memory": "1Gi"},
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
        log.info("iep3_manager: patched StatefulSet %s (store=%s)", name, store_id)
    except ApiException as exc:
        if exc.status == 404:
            _apps_v1.create_namespaced_stateful_set(_NAMESPACE, ss)
            log.info("iep3_manager: created StatefulSet %s (store=%s)", name, store_id)
        else:
            raise


def _apply_iep3_docker(store_id: str) -> None:
    if _docker_client is None:
        log.debug("iep3_manager.apply_iep3: no backend available, skipping (store=%s)", store_id)
        return

    import docker.errors  # type: ignore[import-untyped]

    name = _container_name(store_id)
    env = {
        "STORE_ID":                         store_id,
        "WINDOW_SECONDS":                   _WINDOW_SECONDS,
        "DATABASE_URL_SERVER":              _DATABASE_URL_SERVER,
        "SERVER_REDIS_URL":                 _SERVER_REDIS_URL,
        "REID_THRESHOLD":                   _REID_THRESHOLD,
        "GRACE_SECONDS":                    _GRACE_SECONDS,
        "MAX_SPEED_MPS":                    _MAX_SPEED_MPS,
        "POSITION_WEIGHT_AREA":             _POSITION_WEIGHT_AREA,
        "POSITION_WEIGHT_CONF":             _POSITION_WEIGHT_CONF,
        "ORPHAN_SWEEP_INTERVAL_BATCHES":    _ORPHAN_SWEEP_INTERVAL_BATCHES,
        "EXPECTED_CAMERAS_REFRESH_BATCHES": _EXPECTED_CAMERAS_REFRESH_BATCHES,
    }

    try:
        existing = _docker_client.containers.get(name)
        if existing.status == "running":
            log.debug("iep3_manager: IEP3 container %s already running (store=%s)", name, store_id)
            return
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass

    _docker_client.containers.run(
        image=_IEP3_IMAGE,
        name=name,
        environment=env,
        network=_DOCKER_NETWORK,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
        labels={"component": "iep3", "store-id": store_id, "managed-by": "eep"},
    )
    log.info("iep3_manager: started Docker container %s (store=%s)", name, store_id)


def delete_iep3(store_id: str) -> None:
    """Idempotent delete of IEP3 StatefulSet + headless Service for store_id."""
    if _apps_v1 is None:
        _delete_iep3_docker(store_id)
        return

    from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

    name = _ss_name(store_id)
    for delete_fn, kind in (
        (_apps_v1.delete_namespaced_stateful_set, "StatefulSet"),
        (_core_v1.delete_namespaced_service,      "Service"),
    ):
        try:
            delete_fn(name, _NAMESPACE)
            log.info("iep3_manager: deleted %s %s (store=%s)", kind, name, store_id)
        except ApiException as exc:
            if exc.status != 404:
                raise


def _delete_iep3_docker(store_id: str) -> None:
    if _docker_client is None:
        log.debug("iep3_manager.delete_iep3: no backend available, skipping (store=%s)", store_id)
        return

    import docker.errors  # type: ignore[import-untyped]

    name = _container_name(store_id)
    try:
        _docker_client.containers.get(name).remove(force=True)
        log.info("iep3_manager: removed Docker container %s (store=%s)", name, store_id)
    except docker.errors.NotFound:
        pass
