# Edge Deployment — Jetson Orin Nano + k3s

IEP1 (camera ingestion) and IEP2 (local detection/tracking) run on-device.
Everything else (EEP, IEP3, RDS, MSK, S3) runs on AWS — deployed via CDK.

---

## Prerequisites

- Jetson Orin Nano with JetPack 6.x flashed
- AWS account with CDK stacks already deployed (`cdk deploy --all`)
- Jetson has outbound internet access or AWS VPN/PrivateLink to reach MSK and RDS

---

## 1. Install k3s

```bash
curl -sfL https://get.k3s.io | sh -s - \
  --disable traefik \
  --disable servicelb \
  --write-kubeconfig-mode 644

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
```

## 2. Enable NVIDIA GPU in k3s

```bash
sudo nvidia-ctk runtime configure \
  --runtime=containerd \
  --config=/var/lib/rancher/k3s/agent/etc/containerd/config.toml

sudo systemctl restart k3s

kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml

# Label this node so IEP2 can schedule on it
kubectl label node $(hostname) accelerator=nvidia
```

## 3. Build and import images

Build on the Jetson directly (no cross-compilation needed):

```bash
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

Alternatively, push to ECR from a dev machine and pull on Jetson:

```bash
# Dev machine (arm64 build via buildx)
aws ecr get-login-password | docker login --username AWS \
  --password-stdin <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com

docker buildx build --platform linux/arm64 \
  -f services/iep1_ingestion/Dockerfile \
  -t <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/iep1-ingestion:latest \
  --push .

docker buildx build --platform linux/arm64 \
  -f services/iep2_vision/Dockerfile \
  -t <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/iep2-vision:latest \
  --push .
```

If using ECR, update the image tags in `kustomization.yaml`.

## 4. Fill in CDK outputs

After `cdk deploy --all --outputs-file outputs.json`, copy values into:

| File | Field | CDK output |
|------|-------|------------|
| `configmap.yaml` | `VISION_EVENT_BOOTSTRAP_SERVERS` | `RetailEdgeMessaging.KafkaBootstrap` |
| `configmap.yaml` | `EEP_BASE_URL` | `RetailEdgeServices.EepUrl` |
| `secrets.yaml` | `AWS_ACCESS_KEY_ID` | `RetailEdgeServices.EdgeAccessKeyId` |
| `secrets.yaml` | `AWS_SECRET_ACCESS_KEY` | `RetailEdgeServices.EdgeSecretAccessKey` |
| `secrets.yaml` | `S3_BUCKET` | `RetailEdgeServices.FramesBucket` |
| `secrets.yaml` | `DATABASE_URL` | Build from RDS host in AWS Console / Secrets Manager |

Set `IEP1_AUTO_START_STORE_ID` in `configmap.yaml` to your store's UUID.

## 5. Deploy

```bash
kubectl apply -k infra/edge/

# Watch pods come up
kubectl -n retail-edge get pods -w
```

## 6. Verify

```bash
# IEP1 health
kubectl -n retail-edge exec deploy/iaip1-ingestion \
  -- curl -s localhost:8001/health

# IEP2 logs — should show frames consumed from MSK
kubectl -n retail-edge logs -f deploy/iaip2-detector-workers

# Test1 simulator (if test videos available at /app/testing-data/Test1)
kubectl -n retail-edge exec deploy/iaip1-ingestion \
  -- curl -s -X POST localhost:8001/simulators/test1/runs \
     -H "Content-Type: application/json" \
     -d '{"sample_rate_fps": 2.0}'
```

---

## Network requirements

| Destination | Port | Protocol | Used by |
|-------------|------|----------|---------|
| MSK brokers | 9092 | TCP | IEP1, IEP2 → Kafka |
| RDS endpoint | 5432 | TCP | IEP2 → write tracking_history |
| S3 (AWS) | 443 | HTTPS | IEP1 → upload frames |
| EEP ALB | 80 | HTTP | IEP1 → camera health, topology |

All outbound — no inbound ports needed on the Jetson.
