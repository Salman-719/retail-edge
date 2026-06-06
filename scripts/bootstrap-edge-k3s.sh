#!/bin/bash
# Bootstrap a Jetson edge device with k3s and the RetailVision edge stack.
# Usage: sudo ./bootstrap-edge-k3s.sh <store_uuid> <version> <eep_host> <agent_secret>
set -euo pipefail

STORE_UUID=$1
VERSION=$2
EEP_HOST=$3
AGENT_SECRET=$4

echo "=== RetailVision k3s bootstrap for store ${STORE_UUID} ==="

# 1. NTP sync — clocks must be aligned before stream timestamps are meaningful
apt-get install -y chrony
systemctl enable --now chrony
chronyc waitsync 10 0.5 0 30 || {
    echo "ERROR: NTP sync failed — clocks must be synchronized before deployment"
    exit 1
}
echo "[1/7] NTP sync OK"

# 2. Install k3s (single-node, no CNI, no traefik)
#    --bind-address=127.0.0.1: API server loopback-only (R5 — never network-accessible)
curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="v1.29.4+k3s1" \
    K3S_KUBECONFIG_MODE="644" \
    sh -s - \
    --flannel-backend=none \
    --disable-network-policy \
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
#    Assumes NVIDIA drivers already installed via JetPack
apt-get install -y nvidia-container-toolkit
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
k3s kubectl apply -f infra/edge/base/

echo "[5/7] Base manifests applied — waiting for rollout..."
k3s kubectl rollout status deployment/yolo-service  -n retailvision --timeout=120s
k3s kubectl rollout status deployment/reid-service -n retailvision --timeout=120s
k3s kubectl rollout status deployment/iep1-daemon   -n retailvision --timeout=60s
echo "[5/7] Inference services and IEP1 ready"

# 6. Write Edge Agent environment file
mkdir -p /etc/retailvision/certs
cat > /etc/retailvision/edge-agent.env << EOF
EEP_GRPC_URL=${EEP_HOST}:50051
STORE_ID=${STORE_UUID}
AGENT_VERSION=${VERSION}
IEP2_IMAGE=retailvision-iep2:${VERSION}
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
