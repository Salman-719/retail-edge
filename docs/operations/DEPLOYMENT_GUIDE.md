# RetailVision — Definitive Deployment Guide

End-to-end, **from scratch**, for the production stack. Every step lists **where**
to run it, the **exact command**, and the **expected result**. Follow top to
bottom; do not skip.

### Where commands run
- **[LOCAL]** your workstation/laptop. Do **not** assume tools are installed; run
  the prerequisite check below first.
- **[CLOUDSHELL/EC2]** an AWS shell/server. Do **not** assume tools are installed;
  run the prerequisite check below first.
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

### A0. [LOCAL/CLOUDSHELL/EC2] Install and verify prerequisites first

Run this before **any** deployment command. The deployment requires:

- `aws`
- `terraform`
- `kubectl`
- `helm`
- `jq`
- `curl`
- `git`
- `make`
- valid AWS credentials for account `692461731658`
- network access to GitHub/GHCR, AWS APIs, and Terraform/Helm release hosts
- an EC2 Elastic IP quota with room for **five** addresses in the deployment
  region: two for ingress, two for gRPC, and one for WireGuard

From the repo root:

```bash
cd "$HOME/retail-edge"
bash scripts/install-cloud-deploy-tools.sh
```

Or:

```bash
cd "$HOME/retail-edge"
make cloud-eks-prereqs
```

The script detects Linux `x86_64` vs `arm64` and installs the correct binaries for
Terraform, Helm, and kubectl. It also installs basic packages like `jq`, `curl`,
`git`, and `make` using `yum`, `dnf`, or `apt-get`, and installs AWS CLI v2 when
missing. It installs only missing commands. On Amazon Linux it preserves the
preinstalled `curl-minimal` package instead of requesting conflicting full
`curl`; never add `--allowerasing` for this setup. On macOS it uses Homebrew.

Verify manually:

```bash
export PATH="/usr/local/bin:$PATH"
hash -r

command -v aws
command -v terraform
command -v kubectl
command -v helm
command -v jq
command -v curl
command -v git
command -v make

aws --version
terraform version
kubectl version --client
helm version
jq --version
```

AWS credentials must work before continuing:

```bash
export AWS_REGION=eu-west-1

# Local laptop only. In AWS CloudShell/EC2 with an IAM role, leave AWS_PROFILE unset.
# export AWS_PROFILE=adsal

aws sts get-caller-identity

aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-0263D0A3 \
  --region "$AWS_REGION" \
  --query 'Quota.Value' \
  --output text

aws ec2 describe-addresses \
  --region "$AWS_REGION" \
  --query 'Addresses[].{IP:PublicIp,AllocationId:AllocationId,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table
```

Expected account:

```text
692461731658
```

If any command is missing, stop and fix prerequisites. Do not run
`make cloud-eks-deploy` until every command above works.

### A1. Recommended smooth path

Use this path for a fresh deployment or after intentionally tearing down the old
cloud. It avoids the mistakes we already hit: missing Helm locally, wrong
architecture Terraform binary, stale plans, lost CloudShell state, missing image
tags, private GHCR packages, state drift, duplicate fixed-name AWS resources,
Elastic IP exhaustion, dropped gRPC NLB annotations, and `--reuse-values`
carrying broken old values into a first install.

Run from a machine that has AWS access and the repo. **AWS CloudShell in
`eu-west-1` is the safest place** if your laptop is blocked by
`releases.hashicorp.com` geo/WAF responses.

```bash
cd "$HOME"
git clone https://github.com/Salman-719/retail-edge.git 2>/dev/null || true
cd "$HOME/retail-edge"
git checkout deploy/aws-eks
git pull --ff-only origin deploy/aws-eks

bash scripts/install-cloud-deploy-tools.sh

export AWS_REGION=eu-west-1
export OWNER=salman-719
export VERSION=1.3.1   # use the image tag built from this commit
export LETSENCRYPT_EMAIL=ali.salman@edgebot.com
export BUCKET="retailvision-prod-objects-$(aws sts get-caller-identity --query Account --output text)"

# Optional, but required for the IEP6 agent to call OpenAI.
export OPENAI_API_KEY='sk-...'

# If this image tag is not already built, push the release tag and wait for
# GitHub Actions -> Build & Push Images to finish green.
if ! git ls-remote --tags origin "refs/tags/v$VERSION" | grep -q .; then
  git tag "v$VERSION"
  git push origin "v$VERSION"
fi

make cloud-eks-deploy
```

The script:
- checks that the required GHCR images exist and are public for `$VERSION`;
- writes `infra/aws/terraform.tfvars` from the exports above;
- creates an encrypted/versioned S3 Terraform state bucket and DynamoDB lock
  table, then writes an ignored `infra/aws/backend.tf`;
- runs `terraform init`, `validate`, `plan`, and `apply`;
- runs a mandatory AWS/state preflight before planning. It stops if an EKS
  cluster, S3 bucket, IAM resources, secrets, KMS alias, or log group exists
  outside the active remote state;
- calculates EIP demand from the generated Terraform plan. A resumed deployment
  with five existing state-owned EIPs requires zero new EIPs; a fresh deployment
  requires five. It compares only planned creates against remaining quota;
- removes Terraform-managed add-on Helm releases left in `failed` or
  `pending-*` state by an interrupted earlier apply;
- installs the AWS Load Balancer Controller first and waits for both its
  deployment and webhook endpoint before installing any other Service-producing
  add-on;
- installs add-on Helm charts atomically, rolling back a failed chart instead of
  leaving a poisoned Helm release;
- rejects normal deployment plans that delete or replace the EKS cluster, VPC,
  object bucket, or fixed EIPs; intentional destruction must use
  `make cloud-eks-reset`;
- pauses after showing the Terraform plan and requires typing `APPLY`;
- configures `kubectl`;
- writes `retailvision/openai-api-key` if `OPENAI_API_KEY` is set;
- runs `helm lint` and `helm template`;
- installs the chart with Terraform outputs wired into Helm. Application
  resources are preserved on failure, and a full diagnostic report is printed
  instead of hiding the cause behind an atomic rollback; and
- writes reusable exports to `/tmp/retailvision-cloud.env`, including
  `APP_HOST`, `EEP_HOST`, `AGENT_SECRET`, `WG_ENDPOINT`, `PG_HOST`, and
  `REDIS_HOST`;
- writes the cloud CA certificate to `/tmp/retailvision-ca.crt` for edge setup.

If the preflight reports old resources outside state or insufficient EIP
capacity, **do not rerun `terraform apply` and do not reuse a saved plan**. For
the approved wipe-and-redeploy workflow:

```bash
cd "$HOME/retail-edge"
export AWS_REGION=eu-west-1
export CONFIRM_RESET=retailvision-production
make cloud-eks-reset
unset CONFIRM_RESET
make cloud-eks-deploy
```

`cloud-eks-reset` first destroys anything represented by the remote state, then
removes scoped RetailVision orphans from earlier lost-state deployments,
including versioned S3 objects, fixed-name secrets/IAM resources, NLBs, and
RetailVision-tagged EIPs. It retains the Terraform backend bucket and lock table.
It refuses to finish unless the deployment state is empty, then runs the AWS
preflight. Both checks must pass before a new apply begins.

If the reset finishes but reports fewer than five EIPs available, unrelated
addresses are consuming the regional quota. Release unused addresses or request
an EC2-VPC Elastic IP quota increase. Do not remove an address used by another
system.

### A2. [LOCAL] Manual macOS prerequisites

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

### A3. [LOCAL] Get the code

```bash
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
git checkout deploy/aws-eks
```

### A4. [LOCAL] Build & publish the images (GHCR)

```bash
git tag "v$VERSION"
git push origin "v$VERSION"
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

Before installing Helm, verify the required tag exists:
```bash
for image in eep iep3 iep4 iep5 iep6 frontend mlflow; do
  token="$(curl -fsSL "https://ghcr.io/token?service=ghcr.io&scope=repository:salman-719/retailvision/$image:pull" | jq -r .token)"
  curl -fsSL -H "Authorization: Bearer $token" \
    "https://ghcr.io/v2/salman-719/retailvision/$image/manifests/$VERSION" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' >/dev/null &&
    echo "$image:$VERSION OK" || echo "$image:$VERSION MISSING/PRIVATE"
done
```
Do not install Helm until every required cloud image prints `OK`.

### A5. [LOCAL/CLOUDSHELL] Provision EKS infrastructure

For the first deployment, use `make cloud-eks-deploy` from A1. Do not start a
first deployment with bare `terraform init/plan/apply`: the wrapper creates and
selects the persistent S3 backend, checks AWS/state consistency and EIP capacity,
then creates a fresh plan.

The generated input file is `infra/aws/terraform.tfvars` and the generated,
ignored backend declaration is `infra/aws/backend.tf`. Inspect them if needed,
but keep the wrapper as the deployment entry point.

For later infrastructure changes, use Part D3 so the same remote state is
selected before planning.

The wrapper writes these effective values. Leave `app_host`/`eep_host` empty for
`nip.io`, or set real hostnames and Route53 values when using the manual
Terraform variables.
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
**Expect:** an EKS cluster, two stable on-demand nodes, Karpenter, KEDA, AWS Load
Balancer Controller, ingress-nginx, cert-manager, External Secrets,
metrics-server, gp3 StorageClass, Secrets Manager entries, and an S3 bucket.

### A5a. [AWS CloudShell] Alternative when local provider downloads are geo-blocked

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

Install the deploy tools. This is the same prerequisite installer used by the
smooth path:
```bash
cd "$HOME/retail-edge"
bash scripts/install-cloud-deploy-tools.sh
```

Clone the repo:
```bash
cd "$HOME"
git clone https://github.com/Salman-719/retail-edge.git
cd "$HOME/retail-edge"
git checkout deploy/aws-eks
```

Deploy:
```bash
export AWS_REGION=eu-west-1
export OWNER=salman-719
export VERSION=1.3.1
export LETSENCRYPT_EMAIL=aas145@mail.aub.edu
make cloud-eks-deploy
```

The wrapper configures `kubectl` and writes reusable outputs to
`/tmp/retailvision-cloud.env`. Load them with:

```bash
. /tmp/retailvision-cloud.env
```

### A5b. [LOCAL] Set the OpenAI API key (IEP6 agent)

Terraform created a **placeholder** `retailvision/openai-api-key`. Set the real
key so the IEP6 agent works (it's read via External Secrets after install):
```bash
aws secretsmanager put-secret-value --profile adsal --region eu-west-1 \
  --secret-id retailvision/openai-api-key --secret-string 'sk-...'
```
> Skip only if you set `--set iep6.enabled=false` at install (no agent). The
> raw-SQL and EEP-action tools are off by default (`iep6.enableRawSql`,
> `iep6.enableEepActions`).

### A6. [LOCAL] Verify cluster add-ons

```bash
kubectl get nodes -L workload
kubectl get pods -A
kubectl get sc
kubectl -n kube-system get deploy aws-load-balancer-controller metrics-server karpenter
kubectl -n keda get deploy
kubectl -n cert-manager get pods
kubectl -n external-secrets get pods
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$WG_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text
```
**Expect:** two `workload=stable` nodes, add-ons Running, KEDA Running, and `gp3`
as the default StorageClass. The SSM command should print `Online`; user-data may
need 2–5 minutes after Terraform finishes.

Read the generated WireGuard server public key:

```bash
cd "$HOME/retail-edge"
export WG_SERVER_PUBLIC_KEY="$(./scripts/get-wireguard-server-key.sh "$WG_INSTANCE_ID" "$REGION")"
echo "$WG_SERVER_PUBLIC_KEY"
```

### A7. [LOCAL/CLOUDSHELL] Install or retry only the application

The full deployment wrapper runs this automatically after Terraform. If
Terraform and the add-ons succeeded but the application install failed, do not
reset or recreate EKS. Retry only the application:

```bash
cd "$HOME/retail-edge"
export AWS_REGION=eu-west-1
export OWNER=salman-719
export VERSION=1.3.1
export HELM_TIMEOUT=30m
make cloud-app-deploy
```

This command reads all NLB, subnet, S3, host, WireGuard, and secret values from
the active Terraform state. It verifies the load balancer controller, External
Secrets, cert-manager, ClusterSecretStore, and internal CA before installing.
It deliberately does not use `--atomic`: if readiness times out, the failed
pods remain available and the command automatically prints descriptions, logs,
PVCs, certificates, services, endpoints, and recent events.

Run diagnostics again at any time with:

```bash
make cloud-app-diagnose
```

**Expect:** `STATUS: deployed`. EEP runs Alembic at startup, building the schema
through the current head revision, including TimescaleDB hypertables, edge-agent
tables, packed ReID embedding galleries, live identity fields, alert severity,
and the optional IEP3 debug trace table.

For later `helm upgrade` commands, either re-run this full command or include
`--reuse-values`; otherwise Helm will drop the gRPC NLB service annotations that
were supplied by `--set-string`.

### A8. [LOCAL] Verify the platform is live

```bash
kubectl -n retailvision get pods -o wide
kubectl -n retailvision get hpa
kubectl -n retailvision get scaledobject
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

Confirm the live API surface and migrations:
```bash
kubectl -n retailvision exec deploy/eep -- alembic current
kubectl -n retailvision port-forward svc/eep-http 8000:8000 >/tmp/rv-eep-pf.log 2>&1 &
sleep 2
curl -fsS http://localhost:8000/openapi.json | jq -e '
  .paths[
    "/api/store/{slug}/live/overview"
  ] and .paths[
    "/api/store/{slug}/cameras/health"
  ] and .paths[
    "/api/store/{slug}/alerts/active"
  ] and .paths[
    "/api/store/{slug}/analytics/store-series"
  ]'
```
**Expect:** Alembic reports revision `0019` and `jq` returns a truthy object.
After login, Live Monitoring, Analytics, and Alerts should load backend data
without a demo-data banner. Empty values are valid until the edge is connected,
the store has an active version, and IEP3/IEP4/IEP5 have produced data.

Confirm observability/MLOps:
```bash
kubectl -n retailvision get deploy prometheus grafana alertmanager mlflow
kubectl -n retailvision get cm prometheus-config grafana-dashboards alertmanager-config
kubectl -n retailvision get ingress grafana mlflow
kubectl -n retailvision get certificate grafana-tls mlflow-tls
kubectl -n retailvision get endpoints grafana mlflow iep6
kubectl -n retailvision get deploy iep6-agent iep6-scheduler
kubectl -n retailvision get scaledobject iep6-agent
kubectl -n retailvision port-forward svc/prometheus 9090:9090 >/tmp/rv-prometheus.log 2>&1 &
sleep 2
curl -fsS "http://localhost:9090/-/ready"
curl -fsS "http://localhost:9090/api/v1/rules" | jq '.data.groups | length'
curl -fsS "http://localhost:9090/api/v1/query?query=up%7Bjob%3D%22iep6%22%7D" | jq '.data.result'
curl -fsS "http://localhost:9090/api/v1/query?query=sum%28http_requests_inprogress%7Bjob%3D%22iep6-agent%22%7D%29" | jq '.data.result'
```
**Expect:** all four deployments available, Prometheus ready, and a non-zero
rules group count. The IEP6 service query should return value `1`; the
`iep6-agent` in-flight request query should return a numeric series (usually `0`
when idle).

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

IEP6 is routed through the frontend nginx and validates the same JWT plus store
membership used by EEP. The request-serving deployment is `iep6-agent`; scheduled
daily/weekly jobs run only in the singleton `iep6-scheduler`. Confirm an
unauthenticated request is rejected:
```bash
curl -sk -o /dev/null -w "%{http_code}\n" \
  "https://$APP_HOST/api/store/example/agent/reports?type=daily"
```
**Expect:** `401`. The AI Assistant page uses the browser access token and reads
persisted daily and weekly reports from `agent_insights`; it no longer displays
sample reports. Weekly summaries run each Monday at 15 minutes past the configured
daily insight hour.
Do not scale `iep6-scheduler`. KEDA owns the `iep6-agent` HPA by reading
`http_requests_inprogress{job="iep6-agent"}` from Prometheus.

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

### A9. [LOCAL] Verify autoscaling

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

### A10. [LOCAL] Open the app

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
the `iep3`/`iep4`/`iep5` images must be Public — see A4.)

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
| `jetson` | `/etc/nv_tegra_release` present | `:1.3.0` (L4T TensorRT) | yes | **built on the device** (C6) |
| `cuda` | `nvidia-smi` works (not Jetson) | `:1.3.0-cuda` (CI) | yes | discrete NVIDIA laptop/PC |
| `cpu` | no NVIDIA GPU | `:1.3.0-cpu` (CI) | no | dev/low-throughput; Macs too |

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
  (all profiles); **`yolo`/`reid`** `:$VERSION-cpu` and `:$VERSION-cuda` from CI
  for those profiles; `yolo`/`reid` `:$VERSION` (Jetson) built on-device in C6.

### C0.5. [OPTIONAL SIMULATOR] Publish videos as RTSP cameras

For a real simulation without physical cameras, run the standalone root-level
camera simulator on a laptop/server that the edge device can reach on the LAN.
It publishes one RTSP stream per video through MediaMTX, so EEP and the edge see
normal camera URLs.

**On the simulator laptop/server:**

```bash
cd /path/to/retail-edge
cd camera-simulator
cp .env.example .env
./scripts/start.sh
```

The default config publishes Test3 camera 1 and camera 2 as RTSP streams. Test3
contains still frames, so these are static camera feeds. For moving video, switch
the simulator to `streams.test1.csv` or add Test2 videos to `streams.csv`.

The script prints URLs like:

```text
rtsp://192.168.1.45:8554/test3-cam1
rtsp://192.168.1.45:8554/test3-cam2
```

Paste those values into the EEP camera stream URL fields. Use the simulator
machine's LAN IP, not `localhost`, because the edge device must connect to it.

To add more simulated cameras, edit `camera-simulator/streams.csv`:

```csv
# name,source,path
cam1,/videos/Test1/Camera1.mp4,cam1
cam2,/videos/Test1/Camera2.mp4,cam2
cam3,/videos/Test2/Videos/video_camera3.mp4,cam3
```

To run the simulator on an AWS EC2 instance, open inbound TCP `8554` in the
instance security group from the edge device public IP, then use:

```text
rtsp://<ec2-public-ip-or-dns>:8554/test3-cam1
rtsp://<ec2-public-ip-or-dns>:8554/test3-cam2
```

Do not leave RTSP open to the whole internet except for a short demo window; the
standalone simulator is intentionally simple and does not enable authentication.

If a stream does not decode on the edge, switch the simulator to H.264
transcoding:

```bash
cd camera-simulator
sed -i.bak 's/^PUBLISH_MODE=.*/PUBLISH_MODE=h264/' .env
./scripts/restart.sh
```

Verify from the edge after C4/C5:

```bash
sudo k3s kubectl -n retailvision exec deploy/iep1-daemon -- python - <<'PY'
import cv2
for url in ["rtsp://192.168.1.45:8554/test3-cam1", "rtsp://192.168.1.45:8554/test3-cam2"]:
    cap = cv2.VideoCapture(url)
    ok, _ = cap.read()
    cap.release()
    print(url, "OK" if ok else "FAILED")
PY
```

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
made them Public in Part A (A4), skip this. Otherwise uncomment and fill in:
```bash
# export GHCR_USER=salman-719          # your GitHub username
# export GHCR_TOKEN=ghp_xxxxxxxxxxxx   # GitHub Personal Access Token, scope: read:packages
```
Run the bootstrap (installs k3s + NVIDIA plugin + edge manifests + the Edge Agent
systemd service):
```bash
sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" "$VERSION" "$EEP_HOST" "$AGENT_SECRET"
```

The script refuses to start without `DATABASE_URL_SERVER`,
`SERVER_REDIS_URL`, and `/etc/retailvision/certs/ca.crt`. It stores the
credentials in `/etc/retailvision/edge-agent.env` with mode `0600`. The supplied
`VERSION` is also applied to IEP1 and IEP2; YOLO/ReID use `$VERSION-cuda`,
`$VERSION-cpu`, or `$VERSION` for the CUDA, CPU, or Jetson profile respectively.

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
docker build -f services/yolo_service/Dockerfile  -t "ghcr.io/salman-719/retailvision/yolo:${VERSION}" .
docker push "ghcr.io/salman-719/retailvision/yolo:${VERSION}"
docker build -f services/reid_service/Dockerfile -t "ghcr.io/salman-719/retailvision/reid:${VERSION}" .
docker push "ghcr.io/salman-719/retailvision/reid:${VERSION}"
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
already exist in GHCR (for example, the current release is `1.3.0`; the next
release would normally be `1.3.1` or `1.4.0`).

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
  git tag v1.3.0 && git push origin v1.3.0     # CI builds all images + -cpu/-cuda variants
  ```
  > ⚠️ **Wait for ALL matrix jobs to go green before deploying.** Each service is a
  > separate job; deploying while (say) the `eep` job is still running causes
  > `ImagePullBackOff` on that image. Verify the tag exists per image in
  > **Packages**, and set any **newly-created** packages (e.g. `yolo`/`reid`
  > `-cpu`/`-cuda`) to **Public** — new GHCR packages default to **private**.

**3. [LOCAL] Roll out the cloud** (EEP self-applies new Alembic migrations)
```bash
export OWNER=salman-719 REGION=eu-west-1 BUCKET=retailvision-prod-objects-692461731658
export VERSION=1.3.0
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
  --set eep.image.tag="$VERSION" \
  --set iep3.image.tag="$VERSION" \
  --set iep4.image.tag="$VERSION" \
  --set iep5.image.tag="$VERSION" \
  --set iep6.image.tag="$VERSION" \
  --set frontend.image.tag="$VERSION" \
  --set mlflow.image.tag="$VERSION" \
  -n retailvision
kubectl -n retailvision rollout status deploy/eep && kubectl -n retailvision get pods
kubectl -n retailvision set image statefulset -l app=iep4 \
  iep4="ghcr.io/$OWNER/retailvision/iep4:$VERSION"
```
> Keep the explicit image-tag overrides when using `--reuse-values`; otherwise
> Helm can retain the previous release's tags even when `values.yaml` changed.
> IEP3/IEP4 are re-provisioned by EEP per active store — no `iep3.stores` flag in
> normal operation (that's only for `staticProvisioning=true`).
> Existing per-store IEP4 StatefulSets are patched explicitly above so custom
> rule severity starts propagating immediately; future activation also uses the
> new image configured in EEP.
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

**4. [EDGE] Update each store's device only when edge code or image tags changed**
(`git pull` first). If the release changes edge images or edge manifests, re-run
the bootstrap with the same release tag used by the cloud.
- **cpu / cuda**: re-run the bootstrap — it re-applies the overlay at the new tag
  and pulls the new `-cpu`/`-cuda` images:
  ```bash
  cd ~/path/to/retail-edge && git pull
  sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" "$VERSION" "$EEP_HOST" "$AGENT_SECRET"
  ```
- **jetson**: rebuild `yolo`/`reid` on the device at the new tag (C6), then re-run
  the bootstrap.
- IEP2 (per-camera) uses `IEP2_IMAGE` in `/etc/retailvision/edge-agent.env`; the
  bootstrap rewrites it to the version you pass — the next `StartCamera` uses it.

**5. Verify**: `kubectl -n retailvision get pods` (cloud + each edge) all `Running`;
hit `https://$APP_HOST`, then verify Live Monitoring, Analytics, and Alerts.
For releases containing migrations, also run the live API/migration checks in A8.

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
   Deploy only the application:
   ```bash
   export VERSION="$TAG"
   make cloud-app-deploy
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
2. **[LOCAL]** `git pull` then re-run the **A7** helm command (without
   `--create-namespace`). Helm applies only what changed.

### D3. Update infrastructure (Terraform)

Use the same deployment wrapper for infrastructure updates. It reconnects to the
S3 backend, runs the state/AWS preflight, creates a new plan, applies it, and
reconciles Helm afterward.

1. **[CLOUDSHELL]** pull the deployment branch and review the changes:
   ```bash
   cd "$HOME/retail-edge"
   git pull --ff-only origin deploy/aws-eks
   make cloud-eks-prereqs
   export AWS_REGION=eu-west-1
   export OWNER=salman-719
   export VERSION=1.3.1
   export LETSENCRYPT_EMAIL=aas145@mail.aub.edu
   make cloud-eks-deploy
   ```
2. Review the Terraform plan shown by the wrapper before approving it. Do not
   apply an old `.tfplan` after any other Terraform operation or manual AWS
   cleanup; generate a new plan by rerunning the wrapper.

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
sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" "$VERSION" "$EEP_HOST" "$AGENT_SECRET"
```

---

## PART E — Troubleshooting (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `aws ... InvalidClientTokenId` | profile region not enabled (opt-in) | `aws configure set region eu-west-1 --profile adsal` |
| `dnf`/`yum` suggests `--allowerasing` because `curl` conflicts with `curl-minimal` | an older prerequisite script requested full `curl` on Amazon Linux | do not use `--allowerasing`; pull the latest branch and rerun `make cloud-eks-prereqs`, which preserves `curl-minimal` and installs only missing packages |
| `make cloud-eks-deploy` exits `141` immediately after `Success! The configuration is valid.` | an older preflight used early-closing shell pipelines under `pipefail`, so a successful producer received SIGPIPE | pull the latest branch and rerun `make cloud-eks-deploy`; the preflight no longer uses those pipelines and now prints the failing command and line for any real error |
| EIP preflight reports `used=5 available=0 required=5`, while the table lists exactly the five `retailvision-production-*` EIPs | an older guard tried to infer planned EIPs by parsing state text | do not release or reset those EIPs; pull the latest branch and rerun. EIP demand is now read directly from the generated Terraform plan, so a partial resume correctly requires zero new addresses |
| zsh `command not found: --flag` | multi-line paste mangled | paste **one line** at a time |
| Terraform `aws-load-balancer-webhook-service ... no endpoints` | an older deployment installed add-ons in parallel before the controller webhook had endpoints | pull the latest branch and rerun `make cloud-eks-deploy`; it removes the failed release, installs the controller first, and gates every other add-on on a live webhook endpoint |
| Terraform `AddressLimitExceeded` | the deployment needs five EIPs, but old or unrelated addresses consume the regional quota | stop; run the reset workflow below for old RetailVision resources, then release only confirmed-unused unrelated EIPs or request a quota increase |
| Terraform `ResourceExistsException`, `EntityAlreadyExists`, `BucketAlreadyOwnedByYou`, log group already exists, or KMS alias already exists | AWS contains resources from an older deployment that are absent from the active remote Terraform state | do not rerun apply; use `CONFIRM_RESET=retailvision-production make cloud-eks-reset` for the approved wipe, or import every resource when preserving it |
| Terraform `secret ... scheduled for deletion` | an older teardown scheduled a fixed-name Secrets Manager secret for deletion | use the approved reset workflow and wait for its final preflight; do not apply a stale plan |
| Terraform preflight says fewer than five EIPs are available | RetailVision or unrelated EIPs still occupy the regional quota | inspect `aws ec2 describe-addresses`; reset old RetailVision addresses, then release unused unrelated addresses or request quota |
| Terraform warns `Helm uninstall ... resources were kept due to resource policy` for cert-manager CRDs | Helm preserves cert-manager CRDs by design across reinstall/retry | safe to ignore if the final Terraform apply completes successfully |
| Helm `chart requires kubeVersion ... incompatible with Kubernetes v1.30.x-eks-...` | EKS reports a provider-suffixed Kubernetes version; Helm treats it like a prerelease unless the chart allows `-0` | chart `kubeVersion` must be `>=1.26.0-0`; pull latest `deploy/aws-eks` or patch `charts/retailvision/Chart.yaml` before installing |
| Helm reports `context deadline exceeded` | one or more application resources did not become Ready before the timeout; older deployment scripts then erased the evidence with `--atomic` | pull the latest branch and run `VERSION=1.3.1 make cloud-app-deploy`; failed resources are preserved and automatic diagnostics identify the exact pod, certificate, PVC, image, scheduling, or load-balancer failure. Re-run `make cloud-app-diagnose` if needed |
| Public app returns nginx `503 Service Temporarily Unavailable` | ingress/NLB is reachable, but the `frontend` Service has no Ready pod endpoints | run `make cloud-app-diagnose`; fix the reported Pending/ImagePull/secret/migration failure, then rerun `make cloud-app-deploy` |
| Public app returns nginx `504`, while `curl http://frontend/` works inside the namespace | ingress-nginx and the frontend pods are on different nodes, but the EKS node security group blocks the frontend container port (`80`) between nodes | pull the Terraform fix that adds `node_security_group_additional_rules.ingress_nodes_all`, then rerun `make cloud-eks-deploy` with the normal exports |
| `helm ... namespaces "retailvision" not found` on first try | namespace race | include `--create-namespace` (step A7) |
| Pod `ImagePullBackOff`: GHCR `not found` | the chart tag was never built/pushed | trigger **Build & Push Images** with tag `1.3.0` or push Git tag `v1.3.0`; wait for all required jobs to pass, then restart affected deployments |
| Pod `ImagePullBackOff`: GHCR `403 Forbidden` | the GHCR package is private | make the package Public, or configure an `imagePullSecret`; for the current public-image deployment, make all cloud packages Public |
| `ImagePullBackOff` on a **freshly-tagged** image (e.g. `eep:1.1.0`) right after a release | that service's CI job hasn't finished (or failed); other images already pushed | wait for **all** matrix jobs green (check per-image tag in Packages); then `kubectl -n retailvision delete pod -l app=<svc>` to retry. Confirm which tags exist: `curl -s "https://ghcr.io/token?scope=repository:<owner>/retailvision/<svc>:pull&service=ghcr.io"` then query `/v2/.../tags/list` |
| Pod `Pending` "Insufficient cpu" | Karpenter cannot launch enough capacity or limits are too low | check `kubectl -n kube-system logs deploy/karpenter`, AWS quotas, and `karpenter_cpu_limit`; raise limits or allow larger instance families (D3) |
| `relation "tracking_history" does not exist` | Postgres volume not freshly seeded | clean reinstall below (needs an **empty** PVC) |
| `password authentication failed` | stale Postgres volume from an earlier password | clean reinstall below |
| `redis-server-0` stuck `ContainerCreating` | cert not issued yet | wait ~1 min; check `kubectl -n retailvision get certificate` |
| EEP log `Error 111 ... redis-server:6380` | Redis still starting | transient; clears once `redis-server-0` is `Running` |
| `curl /api/...` → `404` | wrong path; real routes are `/api/auth`, `/api/stores`, … | test `/api/stores` (expect `401`) |
| GUI says `Showing demo data — live backend not connected` | an old frontend image is still deployed; current production pages contain no demo fallback | verify the new frontend tag exists, update `frontend.image.tag`, run `helm upgrade`, and wait for `kubectl -n retailvision rollout status deploy/frontend` |
| Live/Analytics/Alerts returns `404` after frontend update | frontend and EEP image tags are out of sync | deploy the matching EEP tag, confirm Alembic reaches `0019`, and inspect the OpenAPI paths using the A8 commands |
| Live Monitoring loads but shows zero people | no fresh reconciled identities exist inside `eep.liveStaleMs`, or IEP3/IEP4 is not running | activate the store version, verify edge camera status and per-store IEP3/IEP4 pods, then inspect `global_identities` and `active_person_state` |
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

### Recover the Load Balancer Webhook Race

For this exact error:

```text
failed calling webhook "mservice.elbv2.k8s.aws"
no endpoints available for service "aws-load-balancer-webhook-service"
```

Do **not** reset the cluster. The successful resources from the partial apply are
already in remote Terraform state. Pull the fixed dependency graph and resume:

```bash
cd "$HOME/retail-edge"
git pull --ff-only origin deploy/aws-eks
make cloud-eks-prereqs

export AWS_REGION=eu-west-1
export OWNER=salman-719
export VERSION=1.3.1
export LETSENCRYPT_EMAIL=aas145@mail.aub.edu

make cloud-eks-deploy
```

The wrapper removes only unhealthy Terraform-managed add-on Helm releases, then
creates a fresh Terraform plan. Type `APPLY` after reviewing it. Terraform keeps
the EKS cluster, VPC, node groups, EIPs, IAM, bucket, and healthy add-ons already
created; it installs or repairs only what remains. The new dependency gate waits
up to 10 minutes for the controller deployment and up to 5 minutes for a real
webhook endpoint before cert-manager, ingress-nginx, KEDA, External Secrets,
metrics-server, or Karpenter can proceed.

### Recover a Cross-Node Ingress 504

Apply the node security-group fix through the guarded deployment wrapper:

```bash
export PATH="/usr/local/bin:$PATH"
export AWS_REGION=eu-west-1
export OWNER=salman-719
export VERSION=1.3.1
export LETSENCRYPT_EMAIL=aas145@mail.aub.edu
cd "$HOME/retail-edge"
git pull --ff-only origin deploy/aws-eks
make cloud-eks-deploy
curl -I https://app.52.17.97.51.nip.io
```

The plan should add the node security-group self-ingress rule. Review it and do
not approve if it proposes unrelated destructive changes.

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

### Recover a Partial or Lost-State EKS Apply

The combination of `AddressLimitExceeded` plus existing secrets, IAM resources,
bucket, log group, or KMS alias means the account and active state disagree. A
successful resource from the failed apply may be in remote state, while older
resources may exist only in AWS. Deleting one error at a time and repeatedly
applying the old plan makes the drift worse.

For this project, the approved recovery is a full reset and clean redeploy:

```bash
cd "$HOME/retail-edge"
git pull --ff-only origin deploy/aws-eks
make cloud-eks-prereqs

export AWS_REGION=eu-west-1
export CONFIRM_RESET=retailvision-production
make cloud-eks-reset
unset CONFIRM_RESET
```

The reset is intentionally destructive. It removes the RetailVision EKS
deployment, application data, object bucket contents, secrets, fixed-name IAM
resources, load balancers, and tagged EIPs. It retains only the S3 Terraform
backend and DynamoDB lock table.

EKS node-group and cluster deletion can take 20-40 minutes. Leave the reset
running while it prints `Waiting for EKS node group ...` or
`Waiting for EKS cluster ...`. To inspect it without interfering, open a second
CloudShell tab and run:

```bash
export AWS_REGION=eu-west-1
ps -ef | grep -E '[a]ws eks wait|[r]eset-cloud-eks'
aws eks list-nodegroups \
  --cluster-name retailvision-production \
  --region "$AWS_REGION" \
  --output table 2>/dev/null || true
aws eks describe-cluster \
  --name retailvision-production \
  --region "$AWS_REGION" \
  --query 'cluster.status' \
  --output text 2>/dev/null || echo "cluster deleted"
```

The reset ends by running the preflight. Continue only when it prints:

```text
Terraform state is empty. Confirming AWS preflight before redeploying:
AWS/Terraform preflight passed.
```

Then create a **new** plan and deployment:

```bash
export OWNER=salman-719
export VERSION=1.3.1
export LETSENCRYPT_EMAIL=aas145@mail.aub.edu
make cloud-eks-deploy
```

If the final preflight still reports insufficient EIP capacity, list all
addresses and resolve the quota before deploying:

```bash
aws ec2 describe-addresses \
  --region "$AWS_REGION" \
  --query 'Addresses[].{IP:PublicIp,AllocationId:AllocationId,AssociationId:AssociationId,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table
```

Do not release an EIP unless you have confirmed that it is unused and does not
belong to another system.

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
Then re-run **A8**. EEP rebuilds the schema through the current Alembic head on
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

For the approved complete wipe, use the repository reset command. It reconnects
to the remote backend, destroys state-owned resources, and cleans scoped
RetailVision resources left by older lost-state deployments.

**This permanently deletes the cloud deployment and its data.**

```bash
cd "$HOME/retail-edge"
git checkout deploy/aws-eks
git pull --ff-only origin deploy/aws-eks
make cloud-eks-prereqs

export AWS_REGION=eu-west-1
export CONFIRM_RESET=retailvision-production
make cloud-eks-reset
unset CONFIRM_RESET
```

Expected final line:

```text
AWS/Terraform preflight passed.
```

The reset retains `retailvision-tfstate-<account>-<region>` and the DynamoDB lock
table so future sessions reconnect to the same state location. Immediately before
that line it also confirms that Terraform state is empty. Redeploy with Part A1.

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
  `/api/agent`; the only manual step is setting the OpenAI key — **Part A, step A5b**.
  Contract + tools: `docs/services/IEP6_AGENT.md`.
