# Edge Deployment Guide — Jetson Orin Nano

Deploy IEP1 (camera ingestion) and IEP2 (local detection/tracking) on a Jetson Orin Nano running k3s. Each Jetson serves one store, supporting 3–4 cameras.

---

## Prerequisites

- Jetson Orin Nano with JetPack 6.x flashed (Ubuntu 22.04)
- SSH access to the device
- Cloud deployment complete (`MASTER_IP` and `VISION_INTERNAL_TOKEN` from cloud guide)
- Docker installed on a dev machine (for building images)

---

## Step 1 — Flash JetPack

Download NVIDIA SDK Manager on a host Ubuntu machine and flash JetPack 6.x. Complete the first-boot Ubuntu setup wizard. Enable SSH:

```bash
sudo systemctl enable ssh
sudo systemctl start ssh
```

---

## Step 2 — Install k3s

```bash
curl -sfL https://get.k3s.io | sh -s - \
  --disable traefik \
  --disable servicelb \
  --write-kubeconfig-mode 644

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# Confirm running
kubectl get nodes   # should show Ready after ~30s
```

---

## Step 3 — Enable NVIDIA GPU in k3s

k3s v1.35.5 on JetPack 6 **auto-detects the NVIDIA runtime** and adds it to
the generated `config.toml` automatically. No manual containerd configuration
is needed. Simply deploy the device plugin and label the node:

```bash
# Deploy NVIDIA device plugin (exposes nvidia.com/gpu resource to pods)
kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml

# Label node so IEP2 deployment can schedule on it
kubectl label node $(hostname) accelerator=nvidia

# Verify GPU is allocatable
kubectl get node $(hostname) -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['status']['allocatable'])"
# Expect "nvidia.com/gpu": "1" in the output
```

> **Do not run `nvidia-ctk runtime configure`** on k3s v1.35.5+ — it fails
> with `unsupported configure version: 3` and is not needed.
> Do not create `config.toml.tmpl` or `config-v3.toml.tmpl` — editing the
> auto-generated config breaks CNI (`NetworkPluginNotReady`) and requires a
> full k3s reinstall to recover.

---

## Step 4 — Build and import images

Build ARM64 images directly on the Jetson (no cross-compilation needed):

```bash
# On Jetson
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
git checkout codex/salman-marji-alignment

# IEP1
docker build -f services/iep1_ingestion/Dockerfile \
  -t retail-edge/iep1-ingestion:latest .
docker save retail-edge/iep1-ingestion:latest \
  | sudo k3s ctr images import -

# IEP2
docker build -f services/iep2_vision/Dockerfile \
  -t retail-edge/iep2-vision:latest .
docker save retail-edge/iep2-vision:latest \
  | sudo k3s ctr images import -
```

To build faster on a dev machine and push to ECR:

```bash
# On dev machine (Apple Silicon or Linux x86 with buildx)
docker buildx build --platform linux/arm64 \
  -f services/iep1_ingestion/Dockerfile \
  -t <ECR_REGISTRY>/iep1-ingestion:latest --push .

docker buildx build --platform linux/arm64 \
  -f services/iep2_vision/Dockerfile \
  -t <ECR_REGISTRY>/iep2-vision:latest --push .

# Then on Jetson — configure ECR credentials and pull
```

---

## Step 5 — Fill in config and secrets

All three values come from the cloud side. The **store UUID must be the one EEP
generated** when you created the store in the GUI — the *same* UUID the store's
IEP3 pod uses. Get it on the cloud side with:

```sql
-- on the Mac, via the psql pod (see deploy-cloud.md Step 9)
SELECT id, slug, name FROM stores;
```

Edit `infra/edge/configmap.yaml`:
- `IEP1_AUTO_START_STORE_ID` — the store's real UUID (matches the IEP3 pod's `STORE_ID`)
- `EEP_BASE_URL` — `http://<MASTER_IP>`

Edit `infra/edge/secrets.yaml`:
- `VISION_INTERNAL_TOKEN` — must match the cloud value exactly
  (`kubectl -n retail-edge get secret retail-edge-secrets -o jsonpath='{.data.VISION_INTERNAL_TOKEN}' | base64 -d`)

You can set the store UUID and EEP URL with `sed` instead of an editor:

```bash
STORE_UUID=<real-uuid>
MASTER_IP=<cloud-master-ip>
sed -i "s|IEP1_AUTO_START_STORE_ID:.*|IEP1_AUTO_START_STORE_ID: \"$STORE_UUID\"|" infra/edge/configmap.yaml
sed -i "s|EEP_BASE_URL:.*|EEP_BASE_URL: \"http://$MASTER_IP\"|" infra/edge/configmap.yaml
```

> All three — GUI store, cloud IEP3 pod, and this edge config — must share the
> one real UUID, or the edge's data won't link to the store and reconciliation
> won't run.

---

## Step 6 — Deploy

```bash
cd retail-edge
kubectl apply -k infra/edge/

# Watch pods come up
kubectl -n retail-edge get pods -w
```

Expected output after ~2 minutes:
```
NAME                              READY   STATUS    RESTARTS
redpanda-0                        1/1     Running   0
iaip1-ingestion-xxx               1/1     Running   0
iaip2-detector-workers-xxx        1/1     Running   0
```

---

## Step 7 — Verify

```bash
# IEP1 health
kubectl -n retail-edge exec deploy/iaip1-ingestion \
  -- curl -s localhost:8001/health
# {"service": "iep1-ingestion", "status": "ok"}

# IEP2 logs — should show "Camera processor initialised"
kubectl -n retail-edge logs -f deploy/iaip2-detector-workers

# Run Test1 simulator (needs test videos mounted at /app/testing-data/Test1)
kubectl -n retail-edge exec deploy/iaip1-ingestion \
  -- curl -s -X POST localhost:8001/simulators/test1/runs \
     -H "Content-Type: application/json" \
     -d '{"sample_rate_fps": 2.0}'

# Check run status
kubectl -n retail-edge exec deploy/iaip1-ingestion \
  -- curl -s localhost:8001/runs/<RUN_ID>
```

---

## Step 8 — Connect live cameras

Each camera needs an RTSP URL. Trigger live ingestion via:

```bash
kubectl -n retail-edge exec deploy/iaip1-ingestion \
  -- curl -s -X POST localhost:8001/streams/runs \
     -H "Content-Type: application/json" \
     -d '{
       "store_id": "<STORE_UUID>",
       "version_id": "<VERSION_UUID>",
       "cameras": [
         {
           "section_id": "<SECTION_UUID>",
           "camera_id": "<CAMERA_UUID>",
           "camera_config_id": "<CONFIG_UUID>",
           "stream_url": "rtsp://admin:pass@192.168.1.50/stream1",
           "name": "entrance"
         }
       ],
       "sample_rate_fps": 2.0
     }'
```

Or use the auto-start feature: when `IEP1_AUTO_START_STORE_ID` is set, IEP1 fetches the camera topology from EEP on pod startup and begins streaming automatically.

---

## Network requirements

Only outbound connections are needed — no inbound ports on the Jetson.

| Destination | Port | Protocol | Used by |
|-------------|------|----------|---------|
| `MASTER_IP` | 80 | HTTP | IEP2 → EEP tracking-batch POST |
| Camera IP | 554 | RTSP/TCP | IEP1 → camera stream |
| S3 (AWS) | 443 | HTTPS | IEP1 (only if FRAME_STORAGE=s3) |

---

## Applying changes (important)

`kubectl apply -k infra/edge/` only diffs the **YAML manifests**. Two common
changes are invisible to it and need an explicit restart:

| You changed | Why `apply` says "unchanged" | What to run |
|-------------|------------------------------|-------------|
| Rebuilt an image (same `:latest` tag) | Deployment YAML is byte-identical | `rollout restart` the deployment |
| Edited `configmap.yaml` / `secrets.yaml` | Pods read env at startup; live pods keep old values | `apply -k` **then** `rollout restart` |

```bash
kubectl apply -k infra/edge/
kubectl -n retail-edge rollout restart \
  deployment/iaip1-ingestion deployment/iaip2-detector-workers statefulset/redpanda
kubectl -n retail-edge get pods -w
```

> Confirm an edit actually saved before restarting:
> `grep -E "IEP1_AUTO_START_STORE_ID|EEP_BASE_URL" infra/edge/configmap.yaml`

## Updating images

```bash
# Rebuild and reimport (the :latest tag stays the same)
docker build -f services/iep2_vision/Dockerfile -t retail-edge/iep2-vision:latest .
docker save retail-edge/iep2-vision:latest | sudo k3s ctr images import -

# Restart the deployment so the pod picks up the freshly-imported image
# (apply alone won't — the manifest hasn't changed)
kubectl -n retail-edge rollout restart deployment/iaip2-detector-workers
kubectl -n retail-edge rollout status deployment/iaip2-detector-workers
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Redpanda `Argument parse error: unrecognised option '--mode'/'--node-id'/'--set'` | Those are **rpk** flags, not raw `redpanda` flags. The manifest runs `rpk redpanda start --mode dev-container` — make sure `command:` starts with `rpk`, not `redpanda`. |
| IEP2 `KafkaConnectionError: Unable to bootstrap from redpanda...:9092` | Downstream of Redpanda being down. Fix Redpanda first, then `kubectl -n retail-edge rollout restart deployment/iaip2-detector-workers`. |
| IEP2 stuck at `Pending` | `kubectl describe pod` — GPU resource not available; confirm device plugin is running |
| IEP1 camera `offline` | RTSP URL reachable? Try `ffprobe rtsp://...` from the pod |
| Tracking batches not appearing in cloud DB | Check `VISION_INTERNAL_TOKEN` matches cloud; check `kubectl logs iaip2-*` for HTTP errors |
| Redpanda pod OOMKilled | Increase memory limit in `infra/edge/redpanda.yaml` to 768Mi |
| Frame read latency spike | PVC is full — check `kubectl exec redpanda-0 -- df -h /var/lib/redpanda/data` and the frame cache PVC |
