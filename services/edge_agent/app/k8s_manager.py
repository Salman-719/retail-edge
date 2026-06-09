"""k3s (Kubernetes) lifecycle management for the edge pipeline.

Replaces docker_manager.py in the M3-S4 k3s deployment model.

Manages:
  - iep2-{camera_id}   Deployment + ConfigMap  (per-camera, started/stopped per command)

YOLO-service, ReID-service, and IEP1-daemon Deployments are applied once at
device setup (k3s Deployment YAML) — Edge Agent does not create or destroy them.

All functions are synchronous blocking — call from a ThreadPoolExecutor only.
"""
import logging
import os

from kubernetes import client as k8s, config as k8s_config
from kubernetes.client.exceptions import ApiException as K8sApiException

logger = logging.getLogger(__name__)

NAMESPACE  = os.environ.get("K8S_NAMESPACE", "retailvision")
IEP2_IMAGE = os.environ.get("IEP2_IMAGE", "retailvision-iep2:latest")

_apps_v1: k8s.AppsV1Api | None = None
_core_v1: k8s.CoreV1Api | None = None


# ── Client initialisation ──────────────────────────────────────────────────────

def init_k8s_clients() -> None:
    """Load kubeconfig and initialise API clients.

    Tries the k3s kubeconfig path first (systemd service case), then falls back
    to in-cluster service-account config (pod case).

    On dev machines without k3s (no kubeconfig, not inside a pod): logs a
    warning and returns without raising. Clients stay None. The Edge Agent will
    still start and connect to EEP; StartCamera/StopCamera will fail gracefully
    with a clear error rather than crashing the process at startup.
    """
    global _apps_v1, _core_v1
    kubeconfig = os.environ.get("KUBECONFIG", "/etc/rancher/k3s/k3s.yaml")
    try:
        k8s_config.load_kube_config(config_file=kubeconfig)
        logger.info("k8s: loaded kubeconfig from %s", kubeconfig)
    except Exception:
        try:
            k8s_config.load_incluster_config()
            logger.info("k8s: loaded in-cluster config")
        except Exception as exc:
            logger.warning(
                "k8s: no kubeconfig found at %s and not running inside a pod (%s). "
                "StartCamera/StopCamera unavailable. "
                "Set KUBECONFIG env var to a valid kubeconfig to enable k3s operations.",
                kubeconfig, exc,
            )
            return  # leave _apps_v1 and _core_v1 as None — agent still starts
    _apps_v1 = k8s.AppsV1Api()
    _core_v1 = k8s.CoreV1Api()


def is_available() -> bool:
    return _apps_v1 is not None


def _require_k8s(operation: str) -> None:
    """Raise RuntimeError with a clear message if k8s clients are not initialised."""
    if _apps_v1 is None or _core_v1 is None:
        raise RuntimeError(
            f"k8s_manager.{operation}: Kubernetes clients not initialised — "
            "no kubeconfig or in-cluster config was available at startup. "
            "StartCamera/StopCamera require k3s. "
            "On Jetson: ensure k3s is running and KUBECONFIG is set. "
            "On dev: this operation is not supported without k3s."
        )


# ── Resource naming ────────────────────────────────────────────────────────────

def _deployment_name(camera_id: str) -> str:
    return f"iep2-{camera_id}"


def _configmap_name(camera_id: str) -> str:
    return f"camera-{camera_id}"


# ── ConfigMap (camera config + IEP2 env) ──────────────────────────────────────

def apply_camera_configmap(camera_id: str, env_data: dict) -> None:
    """Create or update the ConfigMap that supplies env vars to the IEP2 pod."""
    _require_k8s("apply_camera_configmap")
    cm = k8s.V1ConfigMap(
        metadata=k8s.V1ObjectMeta(
            name=_configmap_name(camera_id),
            namespace=NAMESPACE,
            labels={"camera-id": camera_id, "component": "iep2-config"},
        ),
        data={k: str(v) for k, v in env_data.items()},
    )
    try:
        _core_v1.create_namespaced_config_map(NAMESPACE, cm)
        logger.info("Created ConfigMap  camera=%s", camera_id)
    except K8sApiException as e:
        if e.status == 409:
            _core_v1.patch_namespaced_config_map(_configmap_name(camera_id), NAMESPACE, cm)
            logger.info("Patched ConfigMap  camera=%s", camera_id)
        else:
            raise


# ── IEP2 Deployment ────────────────────────────────────────────────────────────

def apply_iep2_deployment(camera_id: str) -> None:
    """Create or replace the IEP2 Deployment for a camera."""
    _require_k8s("apply_iep2_deployment")
    deployment = _build_iep2_deployment(camera_id)
    try:
        _apps_v1.create_namespaced_deployment(NAMESPACE, deployment)
        logger.info("Created IEP2 Deployment  camera=%s", camera_id)
    except K8sApiException as e:
        if e.status == 409:
            _apps_v1.patch_namespaced_deployment(
                _deployment_name(camera_id), NAMESPACE, deployment
            )
            logger.info("Patched IEP2 Deployment  camera=%s", camera_id)
        else:
            raise


def _build_iep2_deployment(camera_id: str) -> k8s.V1Deployment:
    ipc_vol = k8s.V1Volume(
        name="ipc-sockets",
        host_path=k8s.V1HostPathVolumeSource(
            path="/dev/shm/sockets",
            type="DirectoryOrCreate",
        ),
    )
    frame_vol = k8s.V1Volume(
        name="frame-store",
        host_path=k8s.V1HostPathVolumeSource(
            path="/dev/shm/frames",
            type="DirectoryOrCreate",
        ),
    )
    cloud_ca_vol = k8s.V1Volume(
        name="cloud-ca",
        secret=k8s.V1SecretVolumeSource(
            secret_name="edge-cloud-ca",
            items=[k8s.V1KeyToPath(key="ca.crt", path="ca.crt")],
        ),
    )
    container = k8s.V1Container(
        name="iep2",
        image=IEP2_IMAGE,
        ports=[
            k8s.V1ContainerPort(name="metrics", container_port=9201),
        ],
        env_from=[
            k8s.V1EnvFromSource(
                config_map_ref=k8s.V1ConfigMapEnvSource(
                    name=_configmap_name(camera_id)
                )
            )
        ],
        resources=k8s.V1ResourceRequirements(
            requests={"cpu": "200m", "memory": "256Mi"},
            limits={"cpu": "1000m", "memory": "512Mi"},
        ),
        volume_mounts=[
            k8s.V1VolumeMount(name="ipc-sockets", mount_path="/tmp/sockets"),
            k8s.V1VolumeMount(name="frame-store",  mount_path="/dev/shm/frames"),
            k8s.V1VolumeMount(
                name="cloud-ca",
                mount_path="/etc/retailvision/certs",
                read_only=True,
            ),
        ],
        liveness_probe=k8s.V1Probe(
            _exec=k8s.V1ExecAction(
                command=[
                    "grpc_health_probe",
                    f"-addr=unix:///tmp/sockets/iep2_health_{camera_id}.sock",
                ]
            ),
            initial_delay_seconds=10,
            period_seconds=15,
            failure_threshold=3,
        ),
    )
    return k8s.V1Deployment(
        metadata=k8s.V1ObjectMeta(
            name=_deployment_name(camera_id),
            namespace=NAMESPACE,
            labels={"app": "iep2", "camera-id": camera_id, "component": "iep2"},
        ),
        spec=k8s.V1DeploymentSpec(
            replicas=1,
            selector=k8s.V1LabelSelector(
                match_labels={"app": "iep2", "camera-id": camera_id}
            ),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(
                    labels={"app": "iep2", "camera-id": camera_id, "component": "iep2"},
                    annotations={
                        "prometheus.io/scrape": "true",
                        "prometheus.io/port": "9201",
                    },
                ),
                spec=k8s.V1PodSpec(
                    containers=[container],
                    volumes=[ipc_vol, frame_vol, cloud_ca_vol],
                ),
            ),
        ),
    )


# ── Teardown ───────────────────────────────────────────────────────────────────

def delete_iep2(camera_id: str) -> None:
    """Delete IEP2 Deployment and ConfigMap. Idempotent — safe if already gone."""
    _require_k8s("delete_iep2")
    for delete_fn, name in [
        (_apps_v1.delete_namespaced_deployment, _deployment_name(camera_id)),
        (_core_v1.delete_namespaced_config_map, _configmap_name(camera_id)),
    ]:
        try:
            delete_fn(name, NAMESPACE)
            logger.info("Deleted k8s resource: %s", name)
        except K8sApiException as e:
            if e.status != 404:
                logger.warning("Failed to delete %s: %s", name, e)


# ── State queries ──────────────────────────────────────────────────────────────

def list_active_iep2_deployments() -> list[dict]:
    """Return one dict per active IEP2 Deployment with its ConfigMap data.

    Each dict contains all ConfigMap keys plus 'camera_id'.
    Used by _restore_active_cameras on Edge Agent startup.
    """
    if _apps_v1 is None:
        logger.warning("k8s not initialised — no cameras to restore")
        return []
    result = []
    try:
        deployments = _apps_v1.list_namespaced_deployment(
            NAMESPACE, label_selector="component=iep2"
        )
    except Exception as exc:
        logger.warning("K8s: failed to list IEP2 deployments: %s", exc)
        return []

    for d in deployments.items:
        camera_id = (d.metadata.labels or {}).get("camera-id", "")
        if not camera_id:
            continue
        data: dict = {"camera_id": camera_id}
        try:
            cm = _core_v1.read_namespaced_config_map(_configmap_name(camera_id), NAMESPACE)
            data.update(cm.data or {})
        except K8sApiException:
            pass
        result.append(data)
    return result


def get_active_camera_ids() -> list[str]:
    """Return camera_ids for all active IEP2 Deployments in k3s."""
    if _apps_v1 is None:
        return []
    try:
        deployments = _apps_v1.list_namespaced_deployment(
            NAMESPACE, label_selector="component=iep2"
        )
        return [
            (d.metadata.labels or {})["camera-id"]
            for d in deployments.items
            if (d.metadata.labels or {}).get("camera-id")
        ]
    except Exception as exc:
        logger.warning("K8s: failed to list active cameras: %s", exc)
        return []


def get_camera_k8s_status(camera_id: str) -> str:
    """Query k3s pod phase and return a normalized status string.

    Return values mirror M3-S3 Docker statuses so EEP's R4 handler needs
    no changes: "running" | "starting" | "pending" | "failed" | "not_found" | "unknown"
    """
    if _core_v1 is None:
        return "unknown"
    try:
        pods = _core_v1.list_namespaced_pod(
            NAMESPACE,
            label_selector=f"camera-id={camera_id},component=iep2",
        )
        if not pods.items:
            return "not_found"
        pod = pods.items[0]
        phase = (pod.status.phase or "Unknown")
        if phase == "Running":
            container_statuses = pod.status.container_statuses or []
            if container_statuses and all(cs.ready for cs in container_statuses):
                return "running"
            # Pod running but containers not yet ready
            return "starting"
        if phase == "Pending":
            return "pending"
        if phase == "Failed":
            return "failed"
        return "unknown"
    except Exception as exc:
        logger.warning("K8s status query failed  camera=%s: %s", camera_id, exc)
        return "unknown"
