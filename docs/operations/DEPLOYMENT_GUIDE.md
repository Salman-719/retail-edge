# RetailVision — Definitive Deployment Guide

End-to-end, **from scratch**, for the production stack. Every step lists **where**
to run it, the **exact command**, and the **expected result**. Follow top to
bottom; do not skip.

### Where commands run
- **[LOCAL]** your workstation/laptop (has `aws`, `terraform`, `kubectl`, `helm`,
  and the git repo).
- **[CLOUD]** Amazon EKS, reached from local after `aws eks update-kubeconfig`.
- **[EDGE]** an in-store Jetson device.

### Architecture (what you are building)
- **Cloud**: autoscaling **Amazon EKS** running:
  - **EEP** REST/gRPC control plane, **frontend**, **IEP6**, in-cluster
    **TimescaleDB/PostgreSQL**, **Redis**, Prometheus, Grafana, and MLflow.
  - **EEP** dynamically provisions per-store **IEP3** StatefulSets, **IEP4**
    StatefulSets, and **IEP5** Jobs through the Kubernetes API.
  - A tainted stable on-demand node pool hosts stateful/system workloads.
    Karpenter launches elastic Graviton worker nodes for stateless/per-store work.
  - Two public NLBs with fixed EIPs: HTTPS app/API ingress and edge gRPC `:50051`.
    Object storage = S3. Secrets = AWS Secrets Manager. TLS = cert-manager.
- **Edge**: k3s on a Jetson per store (IEP1 ingest + YOLO/ReID GPU + per-camera
  IEP2), talking to the cloud EEP over TLS gRPC.
- **No domain needed**: public hostnames are `app.<INGRESS_EIP>.nip.io` and
  `eep.<GRPC_EIP>.nip.io`.
- **Images**: GitHub Container Registry, `ghcr.io/<owner>/retailvision/<svc>`.

### Reference values used below (substitute your own)
| Placeholder | This deployment |
|---|---|
| `<profile>` | `adsal` |
| `<region>` | `eu-west-1` |
| `<owner>` (GitHub org/user, lowercase) | `salman-719` |
| `<account>` | `692461731658` |
| `<INGRESS_EIP>` / `<GRPC_EIP>` | filled from Terraform outputs |

> **Rule 1:** paste **one line at a time**. Multi-line commands joined with `\`
> get corrupted by zsh on paste.
>
> **Rule 2:** never paste literal angle-bracket placeholders like `<INGRESS_EIP>` or
> `<GRPC_EIP>` into a shell — `<` and `>` are redirection operators. Instead, set
> shell variables once and use `$INGRESS_EIP`, `$GRPC_EIP`, `$APP_HOST`, `$EEP_HOST`, etc. The commands below already use
> variables; set them at the start of each shell session (workstation, cloud,
> edge):
> ```bash
> export INGRESS_EIP=<from terraform output ingress_eip>
> export GRPC_EIP=<from terraform output grpc_eip>
> export OWNER=salman-719                                    # your GitHub owner (lowercase)
> export REGION=eu-west-1
> export BUCKET=retailvision-prod-objects-692461731658
> ```
> Optional observability/MLOps hostnames (also `*.nip.io`): Grafana at
> `grafana.$INGRESS_EIP.nip.io`, MLflow at `mlflow.$INGRESS_EIP.nip.io`.

---

## PART A — Cloud deployment on EKS (from scratch)

### A1. [LOCAL] Install tools & fix the AWS profile

```bash
brew install awscli terraform
brew install kubectl helm jq
```
Verify credentials. If you get `InvalidClientTokenId`, your profile points at a
non-enabled opt-in region — set it to `eu-west-1`:
```bash
aws configure set region eu-west-1 --profile adsal
aws sts get-caller-identity --profile adsal
```
**Expect:** JSON with `"Account": "692461731658"`. Do not continue until this works.

> If `terraform init` fails locally because `releases.hashicorp.com` returns
> `x-amzn-waf-reason: geo`, run Part A from **AWS CloudShell** instead. CloudShell
> runs inside AWS and avoids the local geo-blocked provider download path. Because
> CloudShell clones from GitHub, commit and push the current `deploy/aws-eks`
> branch before using it.

### A2. [LOCAL] Get the code

```bash
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
git checkout deploy/aws-eks
```

### A3. [LOCAL] Build & publish the images (GHCR)

```bash
git tag v1.2.0
git push origin v1.2.0
```
**Expect:** a "Build & Push Images" run starts in GitHub → **Actions**. Wait until
the cloud matrix jobs are green (≈15–25 min): `eep`, `iep3`, `iep4`, `iep5`,
`iep6`, `frontend`, and `mlflow`. The Jetson `yolo`/`reid` jobs may fail
(arm64/CUDA emulation) — ignore them for cloud (the edge builds those on-device).

Then make the cloud images pullable without credentials:
- GitHub → repo → **Packages** → open each of `eep`, `iep3`, `iep4`, `iep5`,
  `iep6`, `frontend`, `mlflow` → **Package settings → Change visibility →
  Public**. (EEP provisions `iep3`/`iep4`/`iep5` at runtime, so those images must
  be pullable too.)

Before installing Helm, verify the required tag exists. The production chart
currently expects `1.2.0`:
```bash
for image in eep iep3 iep4 iep5 iep6 frontend mlflow; do
  token="$(curl -fsSL "https://ghcr.io/token?service=ghcr.io&scope=repository:salman-719/retailvision/$image:pull" | jq -r .token)"
  curl -fsSL -H "Authorization: Bearer $token" \
    "https://ghcr.io/v2/salman-719/retailvision/$image/manifests/1.2.0" \
    -H 'Accept: application/vnd.oci.image.index.v1+json' >/dev/null &&
    echo "$image:1.2.0 OK" || echo "$image:1.2.0 MISSING/PRIVATE"
done
```
Do not install Helm until every required cloud image prints `OK`.

### A4. [LOCAL] Provision EKS infrastructure (Terraform)

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```
Open `terraform.tfvars` and set these. Leave `app_host`/`eep_host` empty for
`nip.io`, or set real hostnames and Route53 values.
```hcl
aws_region            = "eu-west-1"
environment           = "production"
letsencrypt_email     = "you@example.com"
s3_bucket_name        = "retailvision-prod-objects-692461731658"
cluster_version       = "1.30"
stable_instance_type  = "t4g.large"
stable_node_count     = 2
stable_node_max_count = 4
node_root_volume_gb   = 60
karpenter_cpu_limit   = "200"
wireguard_enabled     = true
wireguard_instance_type = "t4g.nano"
```
Apply:
```bash
export AWS_PROFILE=adsal
terraform init -upgrade -reconfigure
terraform fmt -check -recursive
terraform validate
terraform plan -out eks.tfplan
terraform apply eks.tfplan
```
**Expect:** an EKS cluster, two stable on-demand nodes, Karpenter, AWS Load
Balancer Controller, ingress-nginx, cert-manager, External Secrets,
metrics-server, gp3 StorageClass, Secrets Manager entries, and an S3 bucket.

### A4a. [AWS CloudShell] Alternative when local provider downloads are geo-blocked

Use this path if local `curl -I https://releases.hashicorp.com/...` returns
`x-amzn-waf-reason: geo`.

First push the deployment branch from your laptop:
```bash
cd /Users/alisalman/Desktop/projects/aub/retail-edge
git checkout deploy/aws-eks
git add -A
git commit -m "Migrate cloud deployment to EKS"
git push origin deploy/aws-eks
```

Then open **AWS Console → CloudShell** in `eu-west-1`. If your prompt is root
(`#`) because you ran `sudo -i`, type `exit` to return to the normal CloudShell
user before cloning or running Terraform. CloudShell persists the normal user's
home directory, but `/root` belongs to the replaceable backing machine. Keeping a
local Terraform state under `/root` can lose the state when CloudShell restarts.
The commands below install tools into `/usr/local/bin`, but the repository and
state must remain under `$HOME`.

Install the deploy tools:
```bash
sudo yum install -y unzip tar gzip git jq

curl -fsSL https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip -o /tmp/terraform.zip
unzip -o /tmp/terraform.zip -d /tmp
sudo install -m 0755 /tmp/terraform /usr/local/bin/terraform

curl -fsSL https://get.helm.sh/helm-v3.15.4-linux-amd64.tar.gz -o /tmp/helm.tgz
tar -xzf /tmp/helm.tgz -C /tmp
sudo install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm

curl -fsSL https://s3.us-west-2.amazonaws.com/amazon-eks/1.30.0/2024-05-12/bin/linux/amd64/kubectl -o /tmp/kubectl
sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl

hash -r
terraform version
helm version
kubectl version --client
```

Clone the repo:
```bash
cd "$HOME"
git clone https://github.com/Salman-719/retail-edge.git
cd "$HOME/retail-edge"
git checkout deploy/aws-eks
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` in CloudShell:
```bash
nano terraform.tfvars
```

Use at least:
```hcl
aws_region            = "eu-west-1"
environment           = "production"
letsencrypt_email     = "ali.salman@edgebot.com"
s3_bucket_name        = "retailvision-prod-objects-692461731658"
cluster_version       = "1.30"
stable_instance_type  = "t4g.large"
stable_node_count     = 2
stable_node_max_count = 4
node_root_volume_gb   = 60
karpenter_cpu_limit   = "200"
```

Deploy:
```bash
terraform init -upgrade -reconfigure
terraform fmt -check -recursive
terraform validate
terraform plan -out eks.tfplan
terraform apply eks.tfplan
```

Configure kubectl and record outputs:
```bash
aws eks update-kubeconfig --name "$(terraform output -raw cluster_name)" --region eu-west-1
export INGRESS_EIP="$(terraform output -raw ingress_eip)"
export GRPC_EIP="$(terraform output -raw grpc_eip)"
export APP_HOST="$(terraform output -raw app_host)"
export EEP_HOST="$(terraform output -raw eep_host)"
export AGENT_SECRET="$(terraform output -raw agent_secret)"
export GRPC_EIP_ALLOCATIONS="$(terraform output -json grpc_eip_allocation_ids | jq -r 'join("\\,")')"
export PUBLIC_SUBNET_IDS="$(terraform output -json public_subnet_ids | jq -r 'join("\\,")')"
export VPC_CIDR="$(terraform output -raw vpc_cidr)"
export WG_INSTANCE_ID="$(terraform output -raw wireguard_instance_id)"
export WG_ENDPOINT="$(terraform output -raw wireguard_endpoint)"
```

### A4b. [LOCAL] Set the OpenAI API key (IEP6 agent)

Terraform created a **placeholder** `retailvision/openai-api-key`. Set the real
key so the IEP6 agent works (it's read via External Secrets after install):
```bash
aws secretsmanager put-secret-value --profile adsal --region eu-west-1 \
  --secret-id retailvision/openai-api-key --secret-string 'sk-...'
```
> Skip only if you set `--set iep6.enabled=false` at install (no agent). The
> raw-SQL and EEP-action tools are off by default (`iep6.enableRawSql`,
> `iep6.enableEepActions`).

### A5. [LOCAL] Verify cluster add-ons

```bash
kubectl get nodes -L workload
kubectl get pods -A
kubectl get sc
kubectl -n kube-system get deploy aws-load-balancer-controller metrics-server karpenter
kubectl -n cert-manager get pods
kubectl -n external-secrets get pods
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$WG_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text
```
**Expect:** two `workload=stable` nodes, add-ons Running, and `gp3` as the default
StorageClass. The SSM command should print `Online`; user-data may need 2–5
minutes after Terraform finishes.

Read the generated WireGuard server public key:

```bash
cd "$HOME/retail-edge"
export WG_SERVER_PUBLIC_KEY="$(./scripts/get-wireguard-server-key.sh "$WG_INSTANCE_ID" "$REGION")"
echo "$WG_SERVER_PUBLIC_KEY"
```

### A6. [LOCAL] Install the application (Helm)

Terraform prints `helm_install_hint`; use it, or run the equivalent command:
```bash
cd ../..
helm upgrade --install retailvision ./charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --set global.imageRegistry=ghcr.io/$OWNER/retailvision \
  --set ingress.appHost="$APP_HOST" \
  --set eep.grpcHost="$EEP_HOST" \
  --set eep.grpc.serviceType=LoadBalancer \
  --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-type=external' \
  --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-nlb-target-type=ip' \
  --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-scheme=internet-facing' \
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-eip-allocations=$GRPC_EIP_ALLOCATIONS" \
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-subnets=$PUBLIC_SUBNET_IDS" \
  --set-string "postgres.service.annotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-subnets=$PUBLIC_SUBNET_IDS" \
  --set-string "redis.service.annotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-subnets=$PUBLIC_SUBNET_IDS" \
  --set-string "postgres.service.loadBalancerSourceRanges[0]=$VPC_CIDR" \
  --set-string "redis.service.loadBalancerSourceRanges[0]=$VPC_CIDR" \
  --set s3.bucket="$BUCKET" \
  --set s3.region="$REGION" \
  --set monitoring.grafana.host="grafana.$INGRESS_EIP.nip.io" \
  --set mlflow.host="mlflow.$INGRESS_EIP.nip.io" \
  -n retailvision --create-namespace
```
**Expect:** `STATUS: deployed`. EEP runs Alembic at startup, building the schema
through the current head revision, including TimescaleDB hypertables, edge-agent
tables, packed ReID embedding galleries, and the optional IEP3 debug trace table.

For later `helm upgrade` commands, either re-run this full command or include
`--reuse-values`; otherwise Helm will drop the gRPC NLB service annotations that
were supplied by `--set-string`.

### A7. [LOCAL] Verify the platform is live

```bash
kubectl -n retailvision get pods -o wide
kubectl -n retailvision get hpa
kubectl -n retailvision get svc eep-grpc postgres redis-server
kubectl -n retailvision logs deploy/eep --tail=30
```
**Expect:** Postgres/Redis/Prometheus/Grafana/MLflow on stable nodes; EEP,
frontend, IEP6, and per-store workers schedulable on Karpenter nodes. No `iep3`
or `iep4` exists yet unless a store version has been activated.

The Postgres and Redis Services should each receive an **internal** AWS NLB
hostname. Record them for Part C:

```bash
export PG_HOST="$(kubectl -n retailvision get svc postgres -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
export REDIS_HOST="$(kubectl -n retailvision get svc redis-server -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
test -n "$PG_HOST" && test -n "$REDIS_HOST"
echo "PG_HOST=$PG_HOST"
echo "REDIS_HOST=$REDIS_HOST"
```

These DNS names resolve to private VPC addresses and are unreachable until the
edge WireGuard peer is enrolled.

Confirm **TimescaleDB** is active:
```bash
kubectl -n retailvision exec postgres-0 -- psql -U retailvision -d retailvision -c "\dx" | grep timescaledb
kubectl -n retailvision exec postgres-0 -- psql -U retailvision -d retailvision -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
```

Confirm public app/API:
```bash
curl -sk -o /dev/null -w "%{http_code}\n" "https://$APP_HOST/api/stores"
```
**Expect:** `401` because the API is live and requires auth.

Confirm observability/MLOps:
```bash
kubectl -n retailvision get deploy prometheus grafana alertmanager mlflow
kubectl -n retailvision get cm prometheus-config grafana-dashboards alertmanager-config
kubectl -n retailvision get ingress grafana mlflow
kubectl -n retailvision get certificate grafana-tls mlflow-tls
kubectl -n retailvision get endpoints grafana mlflow iep6
kubectl -n retailvision port-forward svc/prometheus 9090:9090 >/tmp/rv-prometheus.log 2>&1 &
sleep 2
curl -fsS "http://localhost:9090/-/ready"
curl -fsS "http://localhost:9090/api/v1/rules" | jq '.data.groups | length'
curl -fsS "http://localhost:9090/api/v1/query?query=up%7Bjob%3D%22iep6%22%7D" | jq '.data.result'
```
**Expect:** all four deployments available, Prometheus ready, and a non-zero
rules group count. The IEP6 query should return value `1`.

Grafana and MLflow URLs, when set in Helm:
```bash
echo "https://grafana.$INGRESS_EIP.nip.io"
echo "https://mlflow.$INGRESS_EIP.nip.io"
```
Grafana password:
```bash
kubectl -n retailvision get secret retailvision-secrets \
  -o jsonpath='{.data.grafana-admin-password}' | base64 -d; echo
```

Check the public UIs:
```bash
curl -fsSI "https://grafana.$INGRESS_EIP.nip.io/login" | head -1
curl -fsS "https://mlflow.$INGRESS_EIP.nip.io/health"
```
**Expect:** Grafana returns `HTTP/2 200` or `302`; MLflow returns `OK`.

IEP6 is routed through the frontend nginx and now validates the same JWT plus
store membership used by EEP. Confirm an unauthenticated request is rejected:
```bash
curl -sk -o /dev/null -w "%{http_code}\n" \
  "https://$APP_HOST/api/store/example/agent/reports?type=daily"
```
**Expect:** `401`. The AI Assistant page uses the browser access token and reads
persisted daily and weekly reports from `agent_insights`; it no longer displays
sample reports. Weekly summaries run each Monday at 15 minutes past the configured
daily insight hour.
IEP6 stays at one replica while its scheduled insight/alert jobs run in-process.
Do not enable its HPA unless `iep6.schedulerEnabled=false` and scheduling is
moved to a separately managed worker.

Run an MLOps smoke check from the repo root:
```bash
python3 -m venv .venv-mlops
. .venv-mlops/bin/activate
pip install -r mlops/requirements.txt
export PROMETHEUS_URL=http://localhost:9090
export MLFLOW_TRACKING_URI="https://mlflow.$INGRESS_EIP.nip.io"
python mlops/check_state.py --model-name retailvision || true
python mlops/run_promotion.py --model-name retailvision --dry-run
```
`check_state.py` may warn if no model has been registered yet; that is normal on
a fresh deployment.

CI runs the same MLflow server image and smoke-tests `compare_shadow.py` plus
the dry-run promotion orchestrator on pushes and pull requests targeting
`deploy/aws-eks`, `development`, or `production`. Tagged releases still build
and push the multi-architecture `mlflow` image through `build-images.yml`.
Registry promotion remains an explicit operator action; it does not silently
change a production detector image.

### A8. [LOCAL] Verify autoscaling

```bash
kubectl -n retailvision scale deploy/frontend --replicas=20
kubectl get pods -n retailvision -o wide
kubectl get nodes -w
```
**Expect:** extra frontend pods go Pending, Karpenter launches worker capacity,
pods become Running, and idle nodes consolidate later. Restore:
```bash
kubectl -n retailvision scale deploy/frontend --replicas=2
```

### A9. [LOCAL] Open the app

Browse to **`https://$APP_HOST`**. Use **`$EEP_HOST:50051`** for the Jetson edge
bootstrap in Part C. **Cloud is done.**

---

## PART B — Add a store

Do this once per store.

### B1. Create the store record and get its UUID

**[LOCAL]** In the web UI, create the store (you'll give it a name; the system
also assigns a URL **slug**, e.g. `ali-salman`). The UI does **not** show the
UUID, so retrieve it one of these ways:

**Method 1 — query the database (definitive). [LOCAL]:**
```bash
kubectl -n retailvision exec -it postgres-0 -- psql -U retailvision -d retailvision -c "SELECT id, name, slug, created_at FROM stores ORDER BY created_at DESC;"
```
The **`id`** column is the UUID (e.g. `3f2a…-…`). The newest row is at the top.

**Method 2 — browser DevTools. [LOCAL]:** open DevTools → **Network**, reload the
store page, click the `GET /api/store/<slug>/...` (or `GET /api/stores`) request →
**Response** → copy the `"id"` field.

> Note: store **URLs use the slug** (`/api/store/ali-salman/...`); the **UUID** is
> what the per-store workers are keyed on.

### B2. Activate the store → EEP provisions IEP3 + IEP4 automatically

**This is automatic.** When you **activate a store config version** in the UI
(after onboarding cameras/zones), EEP's lifecycle managers provision that store's
workers via the k8s API — no Helm change needed:
- **IEP3** (reconciliation) — a StatefulSet `iep3-<short>` + headless Service.
- **IEP4** (alerts) — a StatefulSet `iep4-<short>`.

(This is why the `eep` ServiceAccount has the `eep-pipeline-manager` Role, and why
the `iep3`/`iep4`/`iep5` images must be Public — see A3.)

**[LOCAL]** Verify after activation:
```bash
kubectl -n retailvision get statefulset,pods -l 'app in (iep3,iep4)'
kubectl -n retailvision logs deploy/eep --tail=30 | grep -Ei "iep3_manager|iep4_manager"
```
**Expect:** `iep3-<short>` and `iep4-<short>` each `1/1 Running`; EEP log shows
`created StatefulSet iep3-… (store=…)` and the same for iep4.

**IEP5** (end-of-shift analytics) is **not** long-running — EEP launches it as a
`batch/v1` Job when a shift closes (`shift_closer.py`). After a shift close:
```bash
kubectl -n retailvision get jobs -l app=iep5
```
**Expect:** a `iep5-<short>-<YYYY-MM-DD>` Job that reaches `Completed` (auto-cleaned
after 24h via `ttlSecondsAfterFinished`).

> **Escape hatch (manual/emergency only):** to pin IEP3 StatefulSets via Helm
> instead of letting EEP manage them, install with
> `--set iep3.staticProvisioning=true --set "iep3.stores={uuid1,uuid2}"`. The
> `iep3.stores` list is the COMPLETE set (Helm makes the workers match it exactly).
> Leave `staticProvisioning=false` (default) for normal operation.

> Capacity: each active store adds an IEP3 + IEP4 pod. If pods go Pending,
> Karpenter should add worker nodes automatically. Check `kubectl get nodes -w`,
> Karpenter logs, and AWS capacity limits before changing node-pool limits.

### B3. Per new store — what changes (and what doesn't)

| Step | What changes per store | What stays the same |
|---|---|---|
| Create store (UI) | new name → new **UUID** + slug | — |
| Cloud IEP3/IEP4 (B2) | EEP creates per-store workers when the config version is activated | `$APP_HOST`, `$EEP_HOST`, `$OWNER`, `$REGION`, `$BUCKET` |
| Edge device (Part C) | **`STORE`** = that store's UUID; runs on **that store's** Jetson | `$EEP_HOST`, `$AGENT_SECRET`, GHCR creds — identical for every store |

So onboarding store N is: (1) create it → get UUID, (2) activate its camera/zone
config version in EEP, (3) on that store's Jetson run Part C with only `STORE`
changed.

---

## PART C — Edge device (per store)

Prerequisite: the **cloud must already be deployed** (Part A) and the **store
created** (Part B) — you need its UUID.

### Device profiles (auto-detected)
The bootstrap **detects the device** and applies the matching kustomize overlay
(`infra/edge/overlays/<profile>`). Override with `EDGE_PROFILE=jetson|cuda|cpu`.

| Profile | Detected when | yolo/reid image | GPU | Notes |
|---|---|---|---|---|
| `jetson` | `/etc/nv_tegra_release` present | `:1.2.0` (L4T TensorRT) | yes | **built on the device** (C6) |
| `cuda` | `nvidia-smi` works (not Jetson) | `:1.2.0-cuda` (CI) | yes | discrete NVIDIA laptop/PC |
| `cpu` | no NVIDIA GPU | `:1.2.0-cpu` (CI) | no | dev/low-throughput; Macs too |

`iep1`/`iep2`/`edge-agent` are identical across profiles.

The edge-to-cloud data path is:

`camera RTSP -> IEP1 sampling -> local Redis/tmpfs -> IEP2 detection/tracking/ReID -> private Postgres + private Redis -> IEP3`

This is intentionally the same contract as `reconfig-edge`:
- EEP gRPC is the control plane that starts/stops cameras.
- IEP2 writes tracking rows directly to cloud Postgres.
- IEP2 publishes `batch_complete` directly to cloud Redis for IEP3.

Do not point `SERVER_REDIS_URL` at the EEP hostname. The EKS chart creates
internal NLBs for Postgres and Redis, reachable only through the Terraform-managed
WireGuard gateway. Neither database is internet-facing.

### C0. Prerequisites

**On the [LOCAL] workstation** (to fetch the agent secret + CA — same tools as Part A):
- `aws` CLI v2 (`aws configure set region eu-west-1 --profile adsal`)
- `terraform`, `kubectl`, `helm`, and this repo cloned.

**On the [EDGE] device:**
- Ubuntu; install the bootstrap/verification tools:
  `sudo apt-get update && sudo apt-get install -y git curl python3 netcat-openbsd`.
- **jetson**: JetPack/NVIDIA drivers installed (ships `nvidia-container-toolkit`).
  **cuda**: NVIDIA driver + `nvidia-smi` working (bootstrap installs the toolkit).
  **cpu**: nothing extra.
- Network egress to: `$EEP_HOST:50051`, the private PostgreSQL endpoint on
  `5432`, the private Redis TLS endpoint on `6380`, `ghcr.io`, and
  `get.k3s.io`; plus RTSP access to each camera, normally TCP `554`.
- Root/sudo. The bootstrap installs k3s itself.
- GHCR images public (or `GHCR_USER`/`GHCR_TOKEN`): `iep1` and `iep2`
  (all profiles); **`yolo`/`reid`** `:1.2.0-cpu` and `:1.2.0-cuda` from CI for
  those profiles; `yolo`/`reid` `:1.2.0` (Jetson) built on-device in C6.

### C1. [LOCAL/CLOUDSHELL] Collect cloud inputs

Read the shared edge token from the running cluster. This works even if the
Terraform state is not available:

```bash
export AGENT_SECRET="$(kubectl -n retailvision get secret retailvision-secrets -o jsonpath='{.data.agent-secret}' | base64 -d)"
export EEP_HOST="eep.18.200.72.111.nip.io"
```

From the repository whose Terraform state owns the EKS deployment:

```bash
export EEP_HOST="$(terraform -chdir=infra/aws output -raw eep_host)"
export WG_INSTANCE_ID="$(terraform -chdir=infra/aws output -raw wireguard_instance_id)"
export WG_ENDPOINT="$(terraform -chdir=infra/aws output -raw wireguard_endpoint)"
export WG_SERVER_PUBLIC_KEY="$(./scripts/get-wireguard-server-key.sh "$WG_INSTANCE_ID" eu-west-1)"
export PG_HOST="$(kubectl -n retailvision get svc postgres -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
export REDIS_HOST="$(kubectl -n retailvision get svc redis-server -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
export POSTGRES_PASSWORD="$(kubectl -n retailvision get secret retailvision-secrets -o jsonpath='{.data.postgres-password}' | base64 -d)"
```
Get the gRPC CA so the edge trusts EEP:
```bash
kubectl -n cert-manager get secret retailvision-ca -o jsonpath='{.data.tls\.crt}' | base64 -d
```
Copy the entire `-----BEGIN CERTIFICATE----- … -----END CERTIFICATE-----` block;
you'll save it as `ca.crt` on the edge in C2. Also have the store **UUID** ready
(from Part B / the `psql` query). Copy `EEP_HOST`, `WG_ENDPOINT`,
`WG_SERVER_PUBLIC_KEY`, `PG_HOST`, `REDIS_HOST`, `AGENT_SECRET`, and the
Postgres password to the edge through your secure commissioning channel.

### C2. [EDGE] Configure WireGuard

Clone the repo on the device:
```bash
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
git checkout deploy/aws-eks
```
Save the CA you copied in C1:
```bash
sudo mkdir -p /etc/retailvision/certs
sudo tee /etc/retailvision/certs/ca.crt >/dev/null   # paste the PEM block, then press Ctrl-D
```

Choose a unique tunnel address per edge device. The first store can use
`10.99.0.2`, the next `10.99.0.3`, and so on:

```bash
export EEP_HOST=eep.18.200.72.111.nip.io             # current EEP gRPC hostname
export STORE=70ed5b0c-6c56-43ac-a9e0-a3a81d0db52f   # the store UUID from Part B
export WG_ENDPOINT='paste-wireguard-endpoint-from-C1'
export WG_SERVER_PUBLIC_KEY='paste-server-public-key-from-C1'
export EDGE_TUNNEL_IP=10.99.0.2
export PG_HOST='paste-postgres-internal-nlb-hostname-from-C1'
export REDIS_HOST='paste-redis-internal-nlb-hostname-from-C1'

# AGENT_SECRET = shared token the Edge Agent sends to authenticate to EEP.
# REQUIRED, same value read from Kubernetes in C1.
export AGENT_SECRET='paste-the-value-from-C1'
```

Configure and start the tunnel:

```bash
sudo bash scripts/bootstrap-edge-wireguard.sh \
  "$WG_ENDPOINT" "$WG_SERVER_PUBLIC_KEY" "$EDGE_TUNNEL_IP"
export EDGE_WG_PUBLIC_KEY="$(sudo cat /etc/wireguard/public.key)"
echo "$EDGE_WG_PUBLIC_KEY"
```

### C3. [LOCAL/CLOUDSHELL] Register the edge peer

Back in the cloud repository, paste the values printed/selected on the edge,
then register the peer:

```bash
export EDGE_WG_PUBLIC_KEY='paste-edge-public-key-from-C2'
export EDGE_TUNNEL_IP=10.99.0.2
export WG_INSTANCE_ID="$(terraform -chdir=infra/aws output -raw wireguard_instance_id)"

./scripts/register-edge-wireguard-peer.sh \
  "$EDGE_WG_PUBLIC_KEY" "$EDGE_TUNNEL_IP" "$WG_INSTANCE_ID" eu-west-1
```

Each edge must have a unique public key and tunnel IP. Re-running the command
with the same key updates that peer idempotently.

The gateway server key and enrolled peers are stored on its encrypted root
volume. Terraform ignores automatic AMI drift to avoid replacing it during
unrelated updates. If you deliberately replace the gateway, repeat C1-C3 for
every edge because the server public key changes.

### C4. [EDGE] Verify the tunnel and bootstrap k3s

Verify the handshake and private NLB routes:

```bash
sudo wg show wg0
getent ahostsv4 "$PG_HOST"
getent ahostsv4 "$REDIS_HOST"
nc -vz "$PG_HOST" 5432
nc -vz "$REDIS_HOST" 6380
```

Set the direct data-plane URLs expected by `reconfig-edge`:

```bash
# Paste the password collected in C1. URL-encode it before placing it in the URL.
read -rsp "Cloud Postgres password: " PG_PASSWORD; echo

export PG_PASSWORD_ENCODED="$(
  PG_PASSWORD="$PG_PASSWORD" python3 -c \
    'import os, urllib.parse; print(urllib.parse.quote(os.environ["PG_PASSWORD"], safe=""))'
)"
export DATABASE_URL_SERVER="postgresql://retailvision:${PG_PASSWORD_ENCODED}@${PG_HOST}:5432/retailvision"
export SERVER_REDIS_URL="rediss://${REDIS_HOST}:6380?ssl_check_hostname=false"
```
GHCR credentials are **only needed if your image packages are PRIVATE**. If you
made them Public in Part A (A3), skip this. Otherwise uncomment and fill in:
```bash
# export GHCR_USER=salman-719          # your GitHub username
# export GHCR_TOKEN=ghp_xxxxxxxxxxxx   # GitHub Personal Access Token, scope: read:packages
```
Run the bootstrap (installs k3s + NVIDIA plugin + edge manifests + the Edge Agent
systemd service):
```bash
sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" 1.2.0 "$EEP_HOST" "$AGENT_SECRET"
```

The script refuses to start without `DATABASE_URL_SERVER`,
`SERVER_REDIS_URL`, and `/etc/retailvision/certs/ca.crt`. It stores the
credentials in `/etc/retailvision/edge-agent.env` with mode `0600`.

### C5. [EDGE] Verify the runtime

```bash
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -n retailvision
sudo k3s kubectl exec -n retailvision deploy/redis-edge -- redis-cli ping
sudo wg show wg0
sudo systemctl status retailvision-edge-agent --no-pager
sudo journalctl -u retailvision-edge-agent -n 100 --no-pager
```

Expect the node to be `Ready`, local Redis to print `PONG`, both private ports
to connect, and `redis-edge`, `iep1-daemon`, `yolo-service`, and `reid-service`
to be `Running`. The agent log must show `Connecting to EEP` without repeated
authentication or TLS errors.

From a cloud-connected shell:

```bash
kubectl -n retailvision logs deploy/eep --since=10m | grep "$STORE"
```

After activating a camera schedule/configuration, verify the per-camera IEP2 pod
and edge-to-cloud batch delivery:

```bash
sudo k3s kubectl get deploy,pods -n retailvision -l component=iep2
sudo k3s kubectl logs -n retailvision -l component=iep2 --tail=100
```

The IEP2 log should contain `Batch stats` without Postgres, Redis TLS, or CA
errors. On the cloud, the store's IEP3 log should show the corresponding batch:

```bash
kubectl -n retailvision logs "statefulset/iep3-${STORE}" --since=10m
```

### C6. [EDGE] Build the GPU images (`yolo`/`reid`) — **`jetson` profile only**, one-time

> Skip C6 + C7 for the **`cpu`** and **`cuda`** profiles — their `yolo`/`reid`
> images (`-cpu`/`-cuda`) are built in CI and pulled automatically. C6/C7 apply
> only to the Jetson L4T/TensorRT images.

The Jetson images are **not** in CI: they use a Jetson L4T base and export a
TensorRT engine at build time (needs a real GPU), so they must be built **on the
Jetson**.

Prereqs on the Jetson:
- Docker's **default runtime must be `nvidia`** (so the build-time TRT export gets
  the GPU). Check and set:
  ```bash
  grep -q '"default-runtime": "nvidia"' /etc/docker/daemon.json || {
    sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
    sudo systemctl restart docker
  }
  ```
- A GitHub **PAT with `write:packages`**.

Build from the **repo root** and push:
```bash
cd ~/path/to/retail-edge
echo "$GHCR_TOKEN" | docker login ghcr.io -u salman-719 --password-stdin
docker build -f services/yolo_service/Dockerfile  -t ghcr.io/salman-719/retailvision/yolo:1.2.0  .
docker push ghcr.io/salman-719/retailvision/yolo:1.2.0
docker build -f services/reid_service/Dockerfile -t ghcr.io/salman-719/retailvision/reid:1.2.0 .
docker push ghcr.io/salman-719/retailvision/reid:1.2.0
```
Then make `retailvision/yolo` and `retailvision/reid` **Public** (GitHub →
Packages), like the others.

### C7. [EDGE] Expose the GPU to k3s

`yolo`/`reid` request `nvidia.com/gpu: 1`; the node must advertise it. k3s uses
its **own** containerd, so set the nvidia runtime as its default via a template
override, then restart:
```bash
# seed the template from the running config, set nvidia as the default runtime:
sudo cp /var/lib/rancher/k3s/agent/etc/containerd/config.toml \
        /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
sudo sed -i 's/default_runtime_name = "runc"/default_runtime_name = "nvidia"/' \
        /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
sudo systemctl restart k3s
# device plugin should now advertise the GPU:
sudo kubectl get node -o jsonpath='{.items[0].status.allocatable}'; echo
```
**Expect:** `nvidia.com/gpu` appears → `yolo`/`reid` schedule and pull. If it's
still absent, the Jetson integrated GPU may need NVIDIA's Jetson-specific device
plugin config — check the device-plugin pod logs
(`kubectl -n kube-system logs ds/nvidia-device-plugin-daemonset`).

---

## PART D — Updating

### D0. Release an update end-to-end (after merging reconfig-edge or ANY change)

The canonical sequence to ship **any** change — new upstream code (e.g. a
`reconfig-edge` merge), config, or chart edits. Pick a new version that does not
already exist in GHCR (e.g. `1.2.1`).

**1. [LOCAL] Bring in changes + reconcile the deploy layer**
```bash
git checkout deploy/aws-eks && git pull
git fetch origin && git merge origin/reconfig-edge      # only if integrating branch updates
```
- Resolve conflicts keeping **our** deploy logic (bootstrap, `infra/edge/*`, the
  EKS/WireGuard/private-NLB files, and `*/Dockerfile` build fixes), while keeping
  the latest `reconfig-edge` **runtime contracts** in IEP1/IEP2/IEP3.
- **If `services/eep/schema.sql` changed**, re-vendor the Postgres seed copy:
  ```bash
  cp services/eep/schema.sql charts/retailvision/files/schema.sql
  ```
- **If the service set changed** (rename/add), update `infra/edge/overlays/*`,
  `.github/workflows/build-images.yml`, and `charts/` accordingly.

**2. [LOCAL] Bump the version (single source of truth) + build images**
- Set the new tag in **`charts/retailvision/values.yaml`** (`eep.image.tag`,
  `iep3.image.tag`, `iep4.image.tag`, `iep5.image.tag`, `iep6.image.tag`,
  `frontend.image.tag`, `mlflow.image.tag`) and in the **`infra/edge/overlays/*`**
  `newTag` values (iep1/yolo/reid). Bump `Chart.yaml` `appVersion`. Commit + push.
- **If you integrated new Alembic migrations**, make sure the chain has a single
  linear head (no duplicate revision numbers) — e.g. renumber a local migration
  that collides with an upstream one, fixing its `down_revision`.
- Trigger the image build:
  ```bash
  git tag v1.2.1 && git push origin v1.2.1     # CI builds all images + -cpu/-cuda variants
  ```
  > ⚠️ **Wait for ALL matrix jobs to go green before deploying.** Each service is a
  > separate job; deploying while (say) the `eep` job is still running causes
  > `ImagePullBackOff` on that image. Verify the tag exists per image in
  > **Packages**, and set any **newly-created** packages (e.g. `yolo`/`reid`
  > `-cpu`/`-cuda`) to **Public** — new GHCR packages default to **private**.

**3. [LOCAL] Roll out the cloud** (EEP self-applies new Alembic migrations)
```bash
export OWNER=salman-719 REGION=eu-west-1 BUCKET=retailvision-prod-objects-692461731658
export APP_HOST="$(terraform -chdir=infra/aws output -raw app_host)"
export EEP_HOST="$(terraform -chdir=infra/aws output -raw eep_host)"
export INGRESS_EIP="$(terraform -chdir=infra/aws output -raw ingress_eip)"
git pull
helm upgrade retailvision ./charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --reuse-values \
  --set global.imageRegistry=ghcr.io/$OWNER/retailvision \
  --set ingress.appHost="$APP_HOST" \
  --set eep.grpcHost="$EEP_HOST" \
  --set s3.bucket="$BUCKET" \
  --set s3.region="$REGION" \
  --set monitoring.grafana.host="grafana.$INGRESS_EIP.nip.io" \
  --set mlflow.host="mlflow.$INGRESS_EIP.nip.io" \
  -n retailvision
kubectl -n retailvision rollout status deploy/eep && kubectl -n retailvision get pods
```
> Tags now come from `values.yaml` (step 2), so no per-image `--set …tag` needed.
> IEP3/IEP4 are re-provisioned by EEP per active store — no `iep3.stores` flag in
> normal operation (that's only for `staticProvisioning=true`).
> Migration note for the `reconfig-edge` ReID alignment: revision `0014` clears
> only `local_centroids` and `global_embeddings` because old single-centroid rows
> cannot be converted to packed embedding heaps. It does **not** wipe stores,
> cameras, `tracking_history`, global trajectories, or analytics tables. After
> deployment, restart active IEP2/IEP3 workers so they repopulate the new gallery
> format.
>
> ⚠️ **Switching Postgres → TimescaleDB itself requires a fresh data volume**, and
> first-time TimescaleDB adoption needs the **clean reinstall** (Part E) so
> Postgres re-seeds. Existing data is lost — back up first if it matters.

**4. [EDGE] Update each store's device** (`git pull` first)
- **cpu / cuda**: re-run the bootstrap — it re-applies the overlay at the new tag
  and pulls the new `-cpu`/`-cuda` images:
  ```bash
  cd ~/path/to/retail-edge && git pull
  sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" 1.2.1 "$EEP_HOST" "$AGENT_SECRET"
  ```
- **jetson**: rebuild `yolo`/`reid` on the device at the new tag (C6), then re-run
  the bootstrap.
- IEP2 (per-camera) uses `IEP2_IMAGE` in `/etc/retailvision/edge-agent.env`; the
  bootstrap rewrites it to the version you pass — the next `StartCamera` uses it.

**5. Verify**: `kubectl -n retailvision get pods` (cloud + each edge) all `Running`;
hit `https://$APP_HOST`.

The granular variants (D1–D5) below cover individual cases.

### D1. Update the application (new code → new image version)

1. **[LOCAL]** merge your changes into `deploy/aws-eks`, then tag & push:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
   Wait for **Actions** to go green (images pushed as `:1.0.1`).
2. **[LOCAL]** set variables, then roll out the new tag:
   ```bash
   export OWNER=salman-719 REGION=eu-west-1 BUCKET=retailvision-prod-objects-692461731658 TAG=1.0.1
   export APP_HOST="$(terraform -chdir=infra/aws output -raw app_host)"
   export EEP_HOST="$(terraform -chdir=infra/aws output -raw eep_host)"
   export INGRESS_EIP="$(terraform -chdir=infra/aws output -raw ingress_eip)"
   git pull
   ```
   Then (one line):
   ```bash
   helm upgrade retailvision ./charts/retailvision -f charts/retailvision/values.production.yaml --reuse-values --set global.imageRegistry=ghcr.io/$OWNER/retailvision --set ingress.appHost="$APP_HOST" --set eep.grpcHost="$EEP_HOST" --set s3.bucket="$BUCKET" --set s3.region="$REGION" --set monitoring.grafana.host="grafana.$INGRESS_EIP.nip.io" --set mlflow.host="mlflow.$INGRESS_EIP.nip.io" --set eep.image.tag=$TAG --set iep3.image.tag=$TAG --set iep4.image.tag=$TAG --set iep5.image.tag=$TAG --set iep6.image.tag=$TAG --set frontend.image.tag=$TAG --set mlflow.image.tag=$TAG -n retailvision
   ```
3. **[LOCAL]** watch the rollout:
   ```bash
   kubectl -n retailvision rollout status deploy/eep
   kubectl -n retailvision get pods
   ```
   **Expect:** new pods replace old ones, all `Running`. EEP re-runs Alembic on
   start (idempotent).

> Keep a single source of truth: bump the default tags in
> `charts/retailvision/values.yaml` (`eep.image.tag`, etc.) and commit, so you
> can drop the per-tag `--set`s.

### D2. Update chart/config only (no new image)

1. **[LOCAL]** edit the chart or `values.production.yaml`, commit & push.
2. **[LOCAL]** `git pull` then re-run the **A6** helm command (without
   `--create-namespace`). Helm applies only what changed.

### D3. Update infrastructure (Terraform)

Run infrastructure updates from the persistent CloudShell checkout/state
described in A0, not from a fresh `/root` checkout.

1. **[CLOUDSHELL]** pull the deployment branch and review the changes:
   ```bash
   cd "$HOME/retail-edge"
   git pull --ff-only origin deploy/aws-eks
   cd infra/aws
   terraform init -reconfigure
   terraform validate
   terraform plan -out update.tfplan
   terraform show update.tfplan
   terraform apply update.tfplan
   ```
2. If the commit also changes `charts/retailvision`, re-run A6 after Terraform.
   Terraform creates AWS resources; Helm applies Kubernetes Services and
   workloads that use them. The private edge data-plane change requires both.

   **Caution:** read the plan before approving. EKS control-plane changes,
   node-group changes, and Karpenter limits can replace or churn capacity. Stateful
   data lives on gp3 PVCs; back up before destructive storage changes.

### D4. Restart a service (no change, just bounce it)

```bash
kubectl -n retailvision rollout restart deploy/eep
kubectl -n retailvision rollout restart deploy/frontend
kubectl -n retailvision rollout restart statefulset/redis-server
```

### D5. Update an edge device

```bash
# [EDGE] keep DATABASE_URL_SERVER and SERVER_REDIS_URL exported, then re-run
# the idempotent bootstrap so manifests, images, CA Secret, and agent code all
# move together:
cd ~/retail-edge
git pull --ff-only origin deploy/aws-eks
sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" 1.2.1 "$EEP_HOST" "$AGENT_SECRET"
```

---

## PART E — Troubleshooting (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `aws ... InvalidClientTokenId` | profile region not enabled (opt-in) | `aws configure set region eu-west-1 --profile adsal` |
| zsh `command not found: --flag` | multi-line paste mangled | paste **one line** at a time |
| Terraform `aws-load-balancer-webhook-service ... no endpoints` | AWS Load Balancer Controller webhook was registered before its pod became Ready | wait for `kubectl -n kube-system rollout status deploy/aws-load-balancer-controller`, verify endpoints, then rerun `terraform apply eks.tfplan` |
| Terraform `secret ... scheduled for deletion` | old k3s destroy scheduled Secrets Manager secrets for deletion; names cannot be recreated yet | restore or force-delete the old secrets, then rerun `terraform apply eks.tfplan` |
| Terraform `secret ... already exists` | one old secret still exists outside current state | import it or delete it; for clean redeploy, force-delete it with the same secrets cleanup command below |
| Terraform warns `Helm uninstall ... resources were kept due to resource policy` for cert-manager CRDs | Helm preserves cert-manager CRDs by design across reinstall/retry | safe to ignore if the final Terraform apply completes successfully |
| Helm `chart requires kubeVersion ... incompatible with Kubernetes v1.30.x-eks-...` | EKS reports a provider-suffixed Kubernetes version; Helm treats it like a prerelease unless the chart allows `-0` | chart `kubeVersion` must be `>=1.26.0-0`; pull latest `deploy/aws-eks` or patch `charts/retailvision/Chart.yaml` before installing |
| Public app returns nginx `503 Service Temporarily Unavailable` | ingress/NLB is reachable, but the `frontend` Service has no Ready pod endpoints | inspect `kubectl -n retailvision get pods,endpoints`, events, and `describe pod`; fix Pending/ImagePull/secret/migration failures before retrying the URL |
| Public app returns nginx `504`, while `curl http://frontend/` works inside the namespace | ingress-nginx and the frontend pods are on different nodes, but the EKS node security group blocks the frontend container port (`80`) between nodes | pull the Terraform fix that adds `node_security_group_additional_rules.ingress_nodes_all`, then run `terraform plan` and `terraform apply` from the CloudShell directory that owns the Terraform state |
| `helm ... namespaces "retailvision" not found` on first try | namespace race | include `--create-namespace` (step A6) |
| Pod `ImagePullBackOff`: GHCR `not found` | the chart tag was never built/pushed | trigger **Build & Push Images** with tag `1.2.0` or push Git tag `v1.2.0`; wait for all required jobs to pass, then restart affected deployments |
| Pod `ImagePullBackOff`: GHCR `403 Forbidden` | the GHCR package is private | make the package Public, or configure an `imagePullSecret`; for the current public-image deployment, make all cloud packages Public |
| `ImagePullBackOff` on a **freshly-tagged** image (e.g. `eep:1.1.0`) right after a release | that service's CI job hasn't finished (or failed); other images already pushed | wait for **all** matrix jobs green (check per-image tag in Packages); then `kubectl -n retailvision delete pod -l app=<svc>` to retry. Confirm which tags exist: `curl -s "https://ghcr.io/token?scope=repository:<owner>/retailvision/<svc>:pull&service=ghcr.io"` then query `/v2/.../tags/list` |
| Pod `Pending` "Insufficient cpu" | Karpenter cannot launch enough capacity or limits are too low | check `kubectl -n kube-system logs deploy/karpenter`, AWS quotas, and `karpenter_cpu_limit`; raise limits or allow larger instance families (D3) |
| `relation "tracking_history" does not exist` | Postgres volume not freshly seeded | clean reinstall below (needs an **empty** PVC) |
| `password authentication failed` | stale Postgres volume from an earlier password | clean reinstall below |
| `redis-server-0` stuck `ContainerCreating` | cert not issued yet | wait ~1 min; check `kubectl -n retailvision get certificate` |
| EEP log `Error 111 ... redis-server:6380` | Redis still starting | transient; clears once `redis-server-0` is `Running` |
| `curl /api/...` → `404` | wrong path; real routes are `/api/auth`, `/api/stores`, … | test `/api/stores` (expect `401`) |
| `certificate retailvision-app-tls` not Ready | Let's Encrypt rate-limited nip.io | re-run A7 with `--set ingress.clusterIssuer=retailvision-ca-issuer` |
| **[EDGE]** bootstrap aborts: `Packages were downgraded ... without --allow-downgrades` (nvidia-container-toolkit) | JetPack already has a newer toolkit | already fixed (script skips it if present) — `git pull` then re-run the bootstrap |
| **[EDGE]** `retailvision-edge-agent.service not found` / namespace empty | bootstrap aborted before steps 4–7 | fix the abort cause above, then re-run the bootstrap (it's idempotent) |
| **[EDGE/CLOUDSHELL]** git pull: `detected dubious ownership` | repo owned by a different user | use the same user that cloned it, or `git config --global --add safe.directory <path>` |
| `iep3-…`/`iep4-…` pod never appears after activating a store | EEP lacks RBAC, or image private, or not `in-cluster` | check `kubectl -n retailvision logs deploy/eep | grep iep[34]_manager`; ensure `eep-pipeline-manager` Role exists and `iep3`/`iep4` images are Public |
| `iep5-…` Job `Error`/`BackoffLimitExceeded` | analytics failed for that shift | `kubectl -n retailvision logs job/iep5-<short>-<date>`; fix data/config, it re-runs on next shift close (or delete the Job to retry) |
| `CREATE EXTENSION timescaledb` error / hypertable missing | Postgres image is stock `postgres`, not TimescaleDB, or volume pre-dates the switch | ensure `postgres.image.repository=timescale/timescaledb`; do the **clean reinstall** (fresh volume) below |
| Grafana login fails | wrong admin password | read it: `kubectl -n retailvision get secret retailvision-secrets -o jsonpath='{.data.grafana-admin-password}' | base64 -d` |
| Prometheus target `iep3` down | IEP3 pod has no scrape annotation / not running | confirm the pod has `prometheus.io/scrape=true` (set by `iep3_manager`) and is `Running` |
| `mlflow` pod `CrashLoopBackOff` | S3 creds/endpoint or PVC issue | `kubectl -n retailvision logs deploy/mlflow`; verify `s3-access-key`/`s3-secret-key` secrets and `s3.bucket` |

### Recover a Cross-Node Ingress 504

Apply the node security-group fix from the CloudShell checkout that owns the live
Terraform state:

```bash
export PATH="/usr/local/bin:$PATH"
export AWS_REGION=eu-west-1
cd "$HOME/retail-edge"
git pull --ff-only origin deploy/aws-eks
cd infra/aws
terraform init -reconfigure
terraform plan -out node-sg-fix.tfplan
terraform apply node-sg-fix.tfplan
curl -I https://app.52.17.97.51.nip.io
```

The plan should add the node security-group self-ingress rule. Review the plan and
do not apply it if it proposes unrelated destructive changes.

If that checkout or its `terraform.tfstate` no longer exists, do **not** run
Terraform from a fresh clone. Apply the narrowly scoped live repair instead:

```bash
export AWS_REGION=eu-west-1
NODE_SG="$(aws ec2 describe-security-groups \
  --region "$AWS_REGION" \
  --filters "Name=tag:karpenter.sh/discovery,Values=retailvision-production" \
  --query "SecurityGroups[?contains(GroupName, 'node')].GroupId | [0]" \
  --output text)"
test -n "$NODE_SG" && test "$NODE_SG" != "None" && echo "Node SG: $NODE_SG"
aws ec2 authorize-security-group-ingress \
  --region "$AWS_REGION" \
  --group-id "$NODE_SG" \
  --ip-permissions "[{\"IpProtocol\":\"-1\",\"UserIdGroupPairs\":[{\"GroupId\":\"$NODE_SG\",\"Description\":\"Allow all pod and node traffic between EKS nodes\"}]}]"
curl -I https://app.52.17.97.51.nip.io
```

After service is restored, recover or rebuild the Terraform state and migrate it
to an S3 backend before making further infrastructure changes.

### Recover a Partial EKS Apply

If Terraform created EKS but failed on Helm releases or Secrets Manager, do not
destroy the cluster immediately. First inspect the controller and clean old
secrets:

```bash
aws eks update-kubeconfig --name "$(terraform output -raw cluster_name)" --region eu-west-1
kubectl -n kube-system get pods,endpoints | grep aws-load-balancer
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller --timeout=180s
```

If `aws-load-balancer-webhook-service` has no endpoints, inspect:

```bash
kubectl -n kube-system describe deploy aws-load-balancer-controller
kubectl -n kube-system logs deploy/aws-load-balancer-controller --tail=100
```

For a clean redeploy after wiping k3s, permanently remove stale Secrets Manager
entries that are pending deletion or left outside Terraform state:

```bash
for s in \
  retailvision/postgres-password \
  retailvision/redis-password \
  retailvision/jwt-secret \
  retailvision/agent-secret \
  retailvision/redis-url \
  retailvision/s3-access-key \
  retailvision/s3-secret-key \
  retailvision/openai-api-key \
  retailvision/grafana-admin-password
do
  aws secretsmanager delete-secret \
    --region eu-west-1 \
    --secret-id "$s" \
    --force-delete-without-recovery 2>/dev/null || true
done
```

Then rerun:

```bash
terraform apply eks.tfplan
```

### Clean reinstall (fresh database)

Postgres seeds `schema.sql` **only on an empty volume**, so a true reset (including
the **first switch to TimescaleDB**) must drop the PVC. **[LOCAL]:**
```bash
helm uninstall retailvision -n retailvision 2>/dev/null
kubectl delete namespace retailvision --ignore-not-found --wait=true
# Belt-and-braces: ensure the Postgres PVC is gone (PVCs can outlive a namespace
# if finalizers hang). Confirm none remain:
kubectl get pvc -A | grep retailvision || echo "no retailvision PVCs (good)"
```
Then re-run **A7**. EEP rebuilds the schema through the current Alembic head on
the fresh TimescaleDB volume, then you re-create the store (Part B).

### Rotate a Secrets Manager value (e.g. a password)

The node can only **read** secrets, so update from **[LOCAL]**:
```bash
aws secretsmanager put-secret-value --profile adsal --region eu-west-1 --secret-id retailvision/<name> --secret-string '<new-value>'
```
Then **[LOCAL]** force a re-sync and restart consumers:
```bash
kubectl -n retailvision annotate externalsecret retailvision-secrets force-sync="$(date +%s)" --overwrite
kubectl -n retailvision rollout restart deploy/eep
```

---

## PART F — Teardown

**[LOCAL]:**
```bash
helm uninstall retailvision -n retailvision 2>/dev/null || true
kubectl delete namespace retailvision --ignore-not-found --wait=true
cd infra/aws
export AWS_PROFILE=adsal
terraform destroy
```
> S3 buckets and gp3 volumes use Retain/versioning — empty/delete them in the
> console if you want them fully gone (otherwise they keep costing).

---

## Appendix — what's automated (no manual steps on a fresh deploy)

A from-scratch `terraform apply` + `helm install` applies all of the following
automatically. The manual `put-secret-value` / `put-bucket-cors` commands in the
troubleshooting section are **only** needed to repair a deployment whose resources
were created *before* these fixes existed.

Helm chart:
- Seeds Postgres from `schema.sql` (initdb ConfigMap); EEP self-migrates (Alembic)
  using `ALEMBIC_DATABASE_URL` (direct to Postgres).
- EEP/IEP3 connect **directly** to Postgres (pgbouncer optional, off in prod).
- Redis TLS via internal-CA cert (`redis-certificate.yaml`); clients use
  `?ssl_cert_reqs=none`.
- S3 endpoint derived from region (`https://s3.<region>.amazonaws.com`) — never an
  empty endpoint.
- Lean single-node profile (single replicas, valid k8s quantities) fits a 2-vCPU
  t4g.large. No chart-managed namespace (so `--create-namespace` is clean).

Terraform (`infra/aws/`):
- **S3 bucket CORS** (GET/HEAD, any origin) so the SPA renders images in-page.
- Secrets Manager seeded with generated passwords + `redis-url` already containing
  `?ssl_cert_reqs=none` + the dedicated S3 IAM user's keys.
- External Secrets syncs `retailvision/*` via the node IAM role.
- cert-manager ClusterIssuers: Let's Encrypt (public ingress) + internal CA
  (edge↔EEP gRPC and Redis).

- **IEP6 (AI agent)** deploys with the chart (`iep6.enabled`, default on) at
  `/api/agent`; the only manual step is setting the OpenAI key — **Part A, step A4b**.
  Contract + tools: `docs/services/IEP6_AGENT.md`.
