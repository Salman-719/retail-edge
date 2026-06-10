#!/bin/bash
# Bootstrap an edge device (Jetson, NVIDIA laptop, or CPU laptop) with k3s and the
# RetailVision edge stack. The device profile is auto-detected.
# Usage:
#   sudo ./bootstrap-edge-k3s.sh \
#     <store_uuid> <version> <eep_grpc_host> <agent_secret>
# Optional env:
#   GHCR_USER, GHCR_TOKEN   (a GitHub PAT with read:packages) for private images
#   EDGE_PROFILE            force jetson|cuda|cpu (skip auto-detection)
# Required env:
#   DATABASE_URL_SERVER     private PostgreSQL URL reachable from the edge
#   SERVER_REDIS_URL        private rediss:// URL reachable from the edge
set -euo pipefail

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 <store_uuid> <version> <eep_grpc_host> <agent_secret>"
    exit 2
fi

STORE_UUID=$1
VERSION=$2
EEP_HOST=$3
AGENT_SECRET=$4
GHCR_USER="${GHCR_USER:-}"
GHCR_TOKEN="${GHCR_TOKEN:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${DATABASE_URL_SERVER:?Set DATABASE_URL_SERVER to the private cloud PostgreSQL URL}"
: "${SERVER_REDIS_URL:?Set SERVER_REDIS_URL to the private cloud rediss:// URL}"

if [ ! -s /etc/retailvision/certs/ca.crt ]; then
    echo "ERROR: /etc/retailvision/certs/ca.crt is missing or empty"
    echo "Copy the RetailVision internal CA certificate before running this bootstrap."
    exit 1
fi

# Detect device profile (override with EDGE_PROFILE=jetson|cuda|cpu):
#   jetson = Jetson integrated GPU (TensorRT)   cuda = discrete NVIDIA GPU
#   cpu    = no NVIDIA GPU
EDGE_PROFILE="${EDGE_PROFILE:-}"
if [ -z "${EDGE_PROFILE}" ]; then
    if [ -e /etc/nv_tegra_release ] || grep -qi jetson /proc/device-tree/model 2>/dev/null; then
        EDGE_PROFILE=jetson
    elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
        EDGE_PROFILE=cuda
    else
        EDGE_PROFILE=cpu
    fi
fi
case "${EDGE_PROFILE}" in jetson|cuda|cpu) ;; *) echo "ERROR: invalid EDGE_PROFILE=${EDGE_PROFILE}"; exit 1;; esac

echo "=== RetailVision k3s bootstrap for store ${STORE_UUID} (profile: ${EDGE_PROFILE}) ==="

# 1. NTP sync — clocks must be aligned before stream timestamps are meaningful
apt-get install -y chrony
systemctl enable --now chrony
chronyc waitsync 10 0.5 0 30 || {
    echo "ERROR: NTP sync failed — clocks must be synchronized before deployment"
    exit 1
}
echo "[1/7] NTP sync OK"

# 1b. (Optional) authenticate k3s/containerd to GHCR for private images.
if [ -n "${GHCR_TOKEN}" ]; then
    mkdir -p /etc/rancher/k3s
    cat > /etc/rancher/k3s/registries.yaml << EOF
configs:
  ghcr.io:
    auth:
      username: ${GHCR_USER}
      password: ${GHCR_TOKEN}
EOF
    chmod 600 /etc/rancher/k3s/registries.yaml
    echo "[1b] GHCR registry credentials written"
fi

# 2. Install k3s (single-node, default flannel CNI, no traefik/servicelb)
#    --bind-address=127.0.0.1: API server loopback-only (R5 — never network-accessible)
#    NOTE: flannel is kept (do NOT pass --flannel-backend=none) or the node stays
#    NotReady and non-hostNetwork pods (yolo/osnet/iep2) never schedule.
curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="v1.29.4+k3s1" \
    K3S_KUBECONFIG_MODE="644" \
    sh -s - \
    --disable=traefik \
    --disable=servicelb \
    --bind-address=127.0.0.1 \
    --node-name="edge-${STORE_UUID:0:8}"

# Wait for k3s to be ready
until k3s kubectl get node &>/dev/null; do
    echo "Waiting for k3s API..."
    sleep 3
done
echo "[2/7] k3s installed — API server bound to 127.0.0.1"

# 3. NVIDIA container toolkit + device plugin — only on GPU profiles.
#    cpu: skipped entirely (the cpu overlay removes the nvidia.com/gpu request).
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
if [ "${EDGE_PROFILE}" = "cpu" ]; then
    echo "[3/7] CPU profile — skipping NVIDIA toolkit + device plugin"
else
    # Install the toolkit only if missing (JetPack already ships a newer one;
    # a forced install would try to downgrade and abort apt).
    if dpkg -s nvidia-container-toolkit >/dev/null 2>&1; then
        echo "  nvidia-container-toolkit already present — skipping install"
    else
        apt-get install -y nvidia-container-toolkit
    fi
    systemctl restart containerd 2>/dev/null || true
    k3s kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml
    echo "[3/7] NVIDIA device plugin installed (${EDGE_PROFILE})"
    echo "  NOTE: if 'nvidia.com/gpu' is not advertised, set the nvidia runtime as"
    echo "        containerd default (DEPLOYMENT_GUIDE C7), then restart k3s."
fi

# 4. Shared host paths for pod IPC (inference ↔ IEP2)
mkdir -p /dev/shm/sockets /dev/shm/frames
chmod 1777 /dev/shm/sockets /dev/shm/frames
echo "[4/7] Shared host paths created"

# 5. Apply the edge manifests for the detected profile (selects yolo/reid image
#    variant + GPU request). Run from the repo root.
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
k3s kubectl apply -k "${REPO_ROOT}/infra/edge/overlays/${EDGE_PROFILE}/"

case "${EDGE_PROFILE}" in
    cpu) INFERENCE_TAG="${VERSION}-cpu" ;;
    cuda) INFERENCE_TAG="${VERSION}-cuda" ;;
    jetson) INFERENCE_TAG="${VERSION}" ;;
esac

# The overlays define profile behavior, while the bootstrap argument is the
# single source of truth for the deployed release.
k3s kubectl set image deployment/iep1-daemon \
    -n retailvision \
    iep1="ghcr.io/salman-719/retailvision/iep1:${VERSION}"
k3s kubectl set image deployment/yolo-service \
    -n retailvision \
    yolo-service="ghcr.io/salman-719/retailvision/yolo:${INFERENCE_TAG}"
k3s kubectl set image deployment/reid-service \
    -n retailvision \
    reid-service="ghcr.io/salman-719/retailvision/reid:${INFERENCE_TAG}"

k3s kubectl create secret generic edge-cloud-ca \
    --namespace retailvision \
    --from-file=ca.crt=/etc/retailvision/certs/ca.crt \
    --dry-run=client -o yaml | k3s kubectl apply -f -

echo "[5/7] Base manifests applied — waiting for rollout (non-fatal)..."
k3s kubectl rollout status deployment/redis-edge    -n retailvision --timeout=90s  || echo "  WARN edge Redis not ready yet"
k3s kubectl rollout status deployment/iep1-daemon   -n retailvision --timeout=90s  || echo "  WARN iep1 not ready yet (check node Ready / images)"
k3s kubectl rollout status deployment/yolo-service  -n retailvision --timeout=120s || echo "  WARN yolo not ready yet (GPU image present/public?)"
k3s kubectl rollout status deployment/reid-service  -n retailvision --timeout=120s || echo "  WARN reid not ready yet (GPU image present/public?)"
echo "[5/7] Rollout checked — continuing (agent install does not depend on pods being Ready)"

# 6. Write Edge Agent environment file
mkdir -p /etc/retailvision/certs
cat > /etc/retailvision/edge-agent.env << EOF
EEP_GRPC_URL=${EEP_HOST}:50051
STORE_ID=${STORE_UUID}
AGENT_VERSION=${VERSION}
IEP2_IMAGE=ghcr.io/salman-719/retailvision/iep2:${VERSION}
WINDOW_SECONDS=60
HEARTBEAT_INTERVAL_S=30
LOCAL_REDIS_URL=redis://redis-edge:6379/0
SERVER_REDIS_URL=${SERVER_REDIS_URL}
DATABASE_URL_SERVER=${DATABASE_URL_SERVER}
GRPC_CA_CERT_PATH=/etc/retailvision/certs/ca.crt
AGENT_SECRET=${AGENT_SECRET}
KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K8S_NAMESPACE=retailvision
EOF
chmod 600 /etc/retailvision/edge-agent.env
echo "[6/7] Edge Agent environment file written"

# 7. Install the Edge Agent in an isolated Python environment, then run it as a
#    systemd service. The agent dials out to EEP; no inbound edge port is opened.
apt-get install -y python3 python3-venv
AGENT_ROOT=/opt/retailvision/edge-agent
install -d "${AGENT_ROOT}/services"
cp -a "${REPO_ROOT}/services/edge_agent" "${AGENT_ROOT}/services/"
touch "${AGENT_ROOT}/services/__init__.py"
python3 -m venv "${AGENT_ROOT}/venv"
"${AGENT_ROOT}/venv/bin/pip" install --upgrade pip
"${AGENT_ROOT}/venv/bin/pip" install -r "${AGENT_ROOT}/services/edge_agent/requirements.txt"
cat > /usr/local/bin/retailvision-edge-agent << EOF
#!/bin/sh
export PYTHONPATH=${AGENT_ROOT}
exec ${AGENT_ROOT}/venv/bin/python -m services.edge_agent.app.main
EOF
chmod 0755 /usr/local/bin/retailvision-edge-agent

cat > /etc/systemd/system/retailvision-edge-agent.service << EOF
[Unit]
Description=RetailVision Thin Edge Agent
After=k3s.service network-online.target chrony.service
Requires=k3s.service

[Service]
EnvironmentFile=/etc/retailvision/edge-agent.env
ExecStart=/usr/local/bin/retailvision-edge-agent
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now retailvision-edge-agent
echo "[7/7] Edge Agent systemd service installed and started"

echo ""
echo "=== k3s bootstrap complete for store ${STORE_UUID} ==="
echo "    EEP_HOST:    ${EEP_HOST}"
echo "    VERSION:     ${VERSION}"
echo "    KUBECONFIG:  /etc/rancher/k3s/k3s.yaml"
echo ""
echo "Next steps:"
echo "  1. Verify: k3s kubectl get pods -n retailvision"
echo "  2. Verify: journalctl -u retailvision-edge-agent -f"
