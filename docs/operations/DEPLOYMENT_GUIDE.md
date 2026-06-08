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
(`#`) because you ran `sudo -i`, either type `exit` to return to the normal
CloudShell user or keep going; the commands below install tools into
`/usr/local/bin` so both users can find them.

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
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
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
```
**Expect:** two `workload=stable` nodes, add-ons Running, and `gp3` as the default
StorageClass.

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
  --set s3.bucket="$BUCKET" \
  --set s3.region="$REGION" \
  --set monitoring.grafana.host="grafana.$INGRESS_EIP.nip.io" \
  --set mlflow.host="mlflow.$INGRESS_EIP.nip.io" \
  -n retailvision --create-namespace
```
**Expect:** `STATUS: deployed`. EEP runs Alembic at startup, building the schema
through revision **0013** including TimescaleDB hypertables.

For later `helm upgrade` commands, either re-run this full command or include
`--reuse-values`; otherwise Helm will drop the gRPC NLB service annotations that
were supplied by `--set-string`.

### A7. [LOCAL] Verify the platform is live

```bash
kubectl -n retailvision get pods -o wide
kubectl -n retailvision get hpa
kubectl -n retailvision get svc eep-grpc
kubectl -n retailvision logs deploy/eep --tail=30
```
**Expect:** Postgres/Redis/Prometheus/Grafana/MLflow on stable nodes; EEP,
frontend, IEP6, and per-store workers schedulable on Karpenter nodes. No `iep3`
or `iep4` exists yet unless a store version has been activated.

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
| `jetson` | `/etc/nv_tegra_release` present | `:1.0.0` (L4T TensorRT) | yes | **built on the device** (C4) |
| `cuda` | `nvidia-smi` works (not Jetson) | `:1.0.0-cuda` (CI) | yes | discrete NVIDIA laptop/PC |
| `cpu` | no NVIDIA GPU | `:1.0.0-cpu` (CI) | no | dev/low-throughput; Macs too |

`iep1`/`iep2`/`edge-agent` are identical across profiles.

### C0. Prerequisites

**On the [LOCAL] workstation** (to fetch the agent secret + CA — same tools as Part A):
- `aws` CLI v2 (`aws configure set region eu-west-1 --profile adsal`)
- `terraform`, `kubectl`, `helm`, and this repo cloned.

**On the [EDGE] device:**
- Ubuntu; `git` + `curl`: `sudo apt-get update && sudo apt-get install -y git curl`.
- **jetson**: JetPack/NVIDIA drivers installed (ships `nvidia-container-toolkit`).
  **cuda**: NVIDIA driver + `nvidia-smi` working (bootstrap installs the toolkit).
  **cpu**: nothing extra.
- Network egress to: `$EEP_HOST:50051` + `:6380`, `ghcr.io`, `get.k3s.io`.
- Root/sudo. The bootstrap installs k3s itself.
- GHCR images public (or `GHCR_USER`/`GHCR_TOKEN`): `iep1`, `iep2`, `edge-agent`
  (all profiles); **`yolo`/`reid`** `:1.0.0-cpu` & `:1.0.0-cuda` from CI for those
  profiles; `yolo`/`reid` `:1.0.0` (Jetson) built on-device in C4.

### C1. [LOCAL] Collect the inputs (agent secret + gRPC CA + store UUID)

```bash
cd ~/path/to/retail-edge/infra/aws
export AWS_PROFILE=adsal AWS_DEFAULT_REGION=eu-west-1
terraform output -raw agent_secret        # copy this — the shared secret
terraform output -raw eep_host            # copy this — edge gRPC hostname
```
Get the gRPC CA so the edge trusts EEP:
```bash
kubectl -n cert-manager get secret retailvision-ca -o jsonpath='{.data.tls\.crt}' | base64 -d
```
Copy the entire `-----BEGIN CERTIFICATE----- … -----END CERTIFICATE-----` block;
you'll save it as `ca.crt` on the edge in C2. Also have the store **UUID** ready
(from Part B / the `psql` query).

### C2. [EDGE] Get the code and bootstrap

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
Set variables:
```bash
export EEP_HOST=eep.34.248.161.113.nip.io            # terraform output eep_host
export STORE=70ed5b0c-6c56-43ac-a9e0-a3a81d0db52f   # the store UUID from Part B

# AGENT_SECRET = shared token the Edge Agent sends to authenticate to EEP.
# REQUIRED, same for every edge. Get the value with:  terraform output -raw agent_secret
export AGENT_SECRET='paste-the-value-from-terraform-output'
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
sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" 1.0.0 "$EEP_HOST" "$AGENT_SECRET"
```
Restart the agent so it picks up the CA:
```bash
sudo systemctl restart retailvision-edge-agent
```

### C3. [EDGE] Verify

```bash
sudo kubectl get pods -n retailvision
journalctl -u retailvision-edge-agent -f
```
**Expect:** `iep1-daemon` `Running` and the journal prints
`heartbeat sent store_id=<UUID>` every 30s (edge ↔ cloud connected). From
**[LOCAL]**, `kubectl -n retailvision logs deploy/eep | grep <STORE-UUID>`
shows it connect. `yolo`/`reid` stay `Pending` until C4 + C5 below.

### C4. [EDGE] Build the GPU images (`yolo`/`reid`) — **`jetson` profile only**, one-time

> Skip C4 + C5 for the **`cpu`** and **`cuda`** profiles — their `yolo`/`reid`
> images (`-cpu`/`-cuda`) are built in CI and pulled automatically. C4/C5 apply
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
docker build -f services/yolo_service/Dockerfile  -t ghcr.io/salman-719/retailvision/yolo:1.0.0  .
docker push ghcr.io/salman-719/retailvision/yolo:1.0.0
docker build -f services/reid_service/Dockerfile -t ghcr.io/salman-719/retailvision/reid:1.0.0 .
docker push ghcr.io/salman-719/retailvision/reid:1.0.0
```
Then make `retailvision/yolo` and `retailvision/reid` **Public** (GitHub →
Packages), like the others.

### C5. [EDGE] Expose the GPU to k3s

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
`reconfig-edge` merge), config, or chart edits. Pick a new version (e.g. `1.1.0`).

**1. [LOCAL] Bring in changes + reconcile the deploy layer**
```bash
git checkout deploy/aws-eks && git pull
git fetch origin && git merge origin/reconfig-edge      # only if integrating branch updates
```
- Resolve conflicts keeping **our** deploy logic (bootstrap, `infra/edge/*`, the
  `*/Dockerfile` build fixes).
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
  git tag v1.2.0 && git push origin v1.2.0     # CI builds all images + -cpu/-cuda variants
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
> ⚠️ **Switching Postgres → TimescaleDB requires a fresh data volume**, and a
> migration that is **incompatible with existing rows** (e.g. the 2048-dim change,
> or first-time TimescaleDB adoption) needs the **clean reinstall** (Part E) so
> Postgres re-seeds. Existing data is lost — back up first if it matters.

**4. [EDGE] Update each store's device** (`git pull` first)
- **cpu / cuda**: re-run the bootstrap — it re-applies the overlay at the new tag
  and pulls the new `-cpu`/`-cuda` images:
  ```bash
  cd ~/path/to/retail-edge && git pull
  sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" 1.1.0 "$EEP_HOST" "$AGENT_SECRET"
  ```
- **jetson**: rebuild `yolo`/`reid` on the device at the new tag (C4), then re-run
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

1. **[LOCAL]** edit `infra/aws/*.tf` (or `terraform.tfvars`).
2. ```bash
   cd infra/aws && export AWS_PROFILE=adsal
   terraform plan      # review carefully — see what will change/replace
   terraform apply
   ```
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
# [EDGE] update inference services to a new image tag:
kubectl -n retailvision set image deployment/yolo-service yolo-service=ghcr.io/salman-719/retailvision/yolo:1.0.1
kubectl -n retailvision set image deployment/reid-service reid-service=ghcr.io/salman-719/retailvision/reid:1.0.1
# IEP2 (per-camera) uses IEP2_IMAGE from the agent env; bump it then:
sudo sed -i 's#retailvision/iep2:.*#retailvision/iep2:1.0.1#' /etc/retailvision/edge-agent.env
sudo systemctl restart retailvision-edge-agent
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
cd /root/retail-edge
git pull --ff-only origin deploy/aws-eks
cd infra/aws
terraform init -reconfigure
terraform plan -out node-sg-fix.tfplan
terraform apply node-sg-fix.tfplan
curl -I https://app.52.17.97.51.nip.io
```

The plan should add the node security-group self-ingress rule. Review the plan and
do not apply it if it proposes unrelated destructive changes.

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
Then re-run **A7**. EEP rebuilds the schema via Alembic (0001→0013) on the fresh
TimescaleDB volume, then you re-create the store (Part B).

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
