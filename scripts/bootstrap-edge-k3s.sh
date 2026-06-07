#!/bin/bash
# Bootstrap a Jetson edge device with k3s and the RetailVision edge stack.
# Usage: sudo ./bootstrap-edge-k3s.sh <store_uuid> <version> <eep_host> <agent_secret>
# Optional env for pulling private GHCR images:
#   GHCR_USER, GHCR_TOKEN   (a GitHub PAT with read:packages)
set -euo pipefail

STORE_UUID=$1
VERSION=$2
EEP_HOST=$3
AGENT_SECRET=$4
GHCR_USER="${GHCR_USER:-}"
GHCR_TOKEN="${GHCR_TOKEN:-}"

echo "=== RetailVision k3s bootstrap for store ${STORE_UUID} ==="

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

# 3. NVIDIA container toolkit + device plugin (Jetson-specific)
#    JetPack already ships the toolkit; only install if missing so we never try to
#    downgrade the (newer) JetPack version, which aborts apt.
if dpkg -s nvidia-container-toolkit >/dev/null 2>&1; then
    echo "[3/7] nvidia-container-toolkit already present — skipping install"
else
    apt-get install -y nvidia-container-toolkit
fi
systemctl restart containerd 2>/dev/null || true
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
k3s kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml
echo "[3/7] NVIDIA device plugin installed"

# 4. Shared host paths for pod IPC (inference ↔ IEP2)
mkdir -p /dev/shm/sockets /dev/shm/frames
chmod 1777 /dev/shm/sockets /dev/shm/frames
echo "[4/7] Shared host paths created"

# 5. Apply base k3s manifests (namespace, RBAC, inference services, IEP1)
#    Manifests live at infra/edge/base/ in the repo (bootstrap-edge-k3s.sh
#    expects to run from the repo root)
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
k3s kubectl apply -k infra/edge/base/

echo "[5/7] Base manifests applied — waiting for rollout (non-fatal)..."
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
IEP2_IMAGE=ghcr.io/your-org/retailvision/iep2:${VERSION}
WINDOW_SECONDS=60
HEARTBEAT_INTERVAL_S=30
LOCAL_REDIS_URL=redis://127.0.0.1:6379
SERVER_REDIS_URL=rediss://${EEP_HOST}:6380
GRPC_CA_CERT_PATH=/etc/retailvision/certs/ca.crt
AGENT_SECRET=${AGENT_SECRET}
KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K8S_NAMESPACE=retailvision
EOF
chmod 600 /etc/retailvision/edge-agent.env
echo "[6/7] Edge Agent environment file written"

# 7. Install thin Edge Agent as systemd service
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
echo "  1. Copy /etc/retailvision/certs/ca.crt from EEP host"
echo "  2. Verify: k3s kubectl get pods -n retailvision"
echo "  3. Verify: journalctl -u retailvision-edge-agent -f"
