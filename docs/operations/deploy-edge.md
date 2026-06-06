# Deploy — Edge Device (k3s on Jetson)

Per-store edge runbook. Each store runs a Jetson with **k3s**: the IEP1 ingestion
daemon, GPU inference services (YOLO, OSNet) over IPC sockets, and per-camera IEP2
vision workers created on demand by the thin Edge Agent. The Edge Agent talks to
the cloud EEP over TLS gRPC and mirrors `StartCamera`/`StopCamera` into k3s.

For the cloud side, see [deploy-aws-cloud.md](deploy-aws-cloud.md).

## Prerequisites

- Jetson with JetPack (NVIDIA drivers installed) and Ubuntu.
- Network egress to `eep.<domain>:50051` (gRPC) and `:6380` (server Redis, TLS).
- Cloud already deployed; you have:
  - `agent_secret` — `terraform -chdir=infra/aws output -raw agent_secret`
  - `ca.crt` — the gRPC CA (see deploy-aws-cloud.md §5)
  - the store UUID (created via the EEP API / web UI)
- Edge images on GHCR: `iep1`, `iep2`, `yolo`, `osnet` (arm64). Build via
  `.github/workflows/build-images.yml`.

## Bootstrap

```bash
# Optional, for private GHCR images:
export GHCR_USER=<github-user>
export GHCR_TOKEN=<PAT with read:packages>

sudo -E bash scripts/bootstrap-edge-k3s.sh \
  <store_uuid> \
  1.0.0 \
  eep.<domain> \
  <agent_secret>
```

What it does:
1. NTP sync (clocks must align with stream timestamps).
2. (Optional) writes `/etc/rancher/k3s/registries.yaml` for GHCR auth.
3. Installs k3s single-node, API server bound to `127.0.0.1` (never network-reachable).
4. Installs the NVIDIA device plugin.
5. Creates IPC host paths (`/dev/shm/sockets`, `/dev/shm/frames`).
6. Applies `infra/edge/base/` via kustomize (`kubectl apply -k`).
7. Writes `/etc/retailvision/edge-agent.env` and installs the systemd Edge Agent.

Then copy the CA:

```bash
sudo cp ca.crt /etc/retailvision/certs/ca.crt
sudo systemctl restart retailvision-edge-agent
```

## Verify

```bash
k3s kubectl get pods -n retailvision        # iep1-daemon, yolo-service, osnet-service Running
journalctl -u retailvision-edge-agent -f    # "heartbeat sent store_id=..." every 30s
```

On the cloud, confirm the store agent is online:

```bash
kubectl -n retailvision logs deploy/eep | grep <store_uuid>
```

## Image registry / tag overrides

`infra/edge/base/kustomization.yaml` pins image tags and lets you point at a
different registry without editing manifests:

```bash
cd infra/edge/base
kustomize edit set image \
  ghcr.io/your-org/retailvision/yolo=ghcr.io/acme/retailvision/yolo:1.2.0
```

The IEP2 image used for per-camera workers is set via `IEP2_IMAGE` in
`/etc/retailvision/edge-agent.env`; update it and restart the agent to roll new
IEP2 pods on the next `StartCamera`.

## Updating edge services

```bash
k3s kubectl set image deployment/yolo-service \
  yolo-service=ghcr.io/your-org/retailvision/yolo:1.0.1 -n retailvision
k3s kubectl rollout status deployment/yolo-service -n retailvision
```
