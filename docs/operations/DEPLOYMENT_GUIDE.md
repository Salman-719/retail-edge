# RetailVision — Definitive Deployment Guide

End-to-end, **from scratch**, for the production stack. Every step lists **where**
to run it, the **exact command**, and the **expected result**. Follow top to
bottom; do not skip.

### Where commands run
- **[LOCAL]** your workstation/laptop (has the `aws` CLI + the git repo).
- **[SERVER]** the cloud EC2 box, reached via SSM (k3s control plane).
- **[EDGE]** an in-store Jetson device.

### Architecture (what you are building)
- **Cloud**: AWS-native **k3s on one EC2 instance** (Graviton, no EKS) running
  EEP (API/gRPC), per-store IEP3, in-cluster Postgres + Redis, and the frontend.
  One Elastic IP fronts everything via k3s ServiceLB. Object storage = S3.
  Secrets = AWS Secrets Manager. TLS = cert-manager.
- **Edge**: k3s on a Jetson per store (IEP1 ingest + YOLO/OSNet GPU + per-camera
  IEP2), talking to the cloud EEP over TLS gRPC.
- **No domain needed**: public hostnames are `app.<EIP>.nip.io` and
  `eep.<EIP>.nip.io` (nip.io resolves any `*.<ip>.nip.io` to that IP).
- **Images**: GitHub Container Registry, `ghcr.io/<owner>/retailvision/<svc>`.

### Reference values used below (substitute your own)
| Placeholder | This deployment |
|---|---|
| `<profile>` | `adsal` |
| `<region>` | `eu-west-1` |
| `<owner>` (GitHub org/user, lowercase) | `salman-719` |
| `<account>` | `692461731658` |
| `<EIP>` (filled in after step 2) | `34.248.161.113` |

> **Rule 1:** paste **one line at a time**. Multi-line commands joined with `\`
> get corrupted by zsh on paste.
>
> **Rule 2:** never paste literal angle-bracket placeholders like `<EIP>` into a
> shell — `<` and `>` are redirection operators (`cannot open EIP`). Instead, set
> shell variables once and use `$EIP` etc. The commands below already use
> variables; set them at the start of each shell session (workstation, server,
> edge):
> ```bash
> export EIP=34.248.161.113                                  # from: terraform output server_public_ip
> export OWNER=salman-719                                    # your GitHub owner (lowercase)
> export REGION=eu-west-1
> export BUCKET=retailvision-prod-objects-692461731658
> ```

---

## PART A — Cloud deployment (from scratch)

### A1. [LOCAL] Install tools & fix the AWS profile

```bash
brew install awscli terraform
brew install --cask session-manager-plugin
```
Verify credentials. If you get `InvalidClientTokenId`, your profile points at a
non-enabled opt-in region — set it to `eu-west-1`:
```bash
aws configure set region eu-west-1 --profile adsal
aws sts get-caller-identity --profile adsal
```
**Expect:** JSON with `"Account": "692461731658"`. Do not continue until this works.

### A2. [LOCAL] Get the code

```bash
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
git checkout deploy/aws-k3s
```

### A3. [LOCAL] Build & publish the images (GHCR)

```bash
git tag v1.0.0
git push origin v1.0.0
```
**Expect:** a "Build & Push Images" run starts in GitHub → **Actions**. Wait
until the `eep`, `iep3`, and `frontend` matrix jobs are green (≈10–20 min). The
`yolo`/`osnet` jobs may fail (arm64/CUDA emulation) — ignore them for cloud.

Then make the cloud images pullable without credentials:
- GitHub → repo → **Packages** → open `eep`, `iep3`, `frontend` →
  **Package settings → Change visibility → Public** (do this for all three).

### A4. [LOCAL] Provision infrastructure (Terraform)

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```
Open `terraform.tfvars` and set exactly these (leave `app_host`/`eep_host` empty):
```hcl
aws_region        = "eu-west-1"
environment       = "production"
# Real email YOU control — Let's Encrypt sends cert expiry/renewal notices here.
# Not public, need not match any domain. e.g. ali.salman@edgebot.com
letsencrypt_email = "you@example.com"
s3_bucket_name    = "retailvision-prod-objects-692461731658"   # must be globally unique
git_repo_url      = "https://github.com/Salman-719/retail-edge.git"   # must be PUBLIC
git_branch        = "deploy/aws-k3s"
server_instance_type = "t4g.large"
agent_count       = 0
```
Apply:
```bash
export AWS_PROFILE=adsal
terraform init
terraform apply        # review, then type:  yes
```
**Expect:** ~2–3 min; ends with `Apply complete!` and an Outputs block. Record:
```bash
terraform output server_public_ip        # this is <EIP>
terraform output app_host                # app.<EIP>.nip.io
terraform output eep_host                # eep.<EIP>.nip.io
terraform output -raw agent_secret       # save for edge devices (secret)
```

### A5. [LOCAL → SERVER] Wait for the server to finish bootstrapping

```bash
aws ssm start-session --target $(terraform output -raw server_instance_id)
```
You are now **[SERVER]** (prompt `root@ip-...`). The instance auto-runs
`scripts/bootstrap-cloud-k3s.sh`. Watch it finish:
```bash
sudo tail -n 20 /var/log/cloud-init-output.log
```
**Expect:** the last lines include `=== cloud k3s bootstrap complete ===`.
If it's still running, wait and re-run the tail. Then:
```bash
sudo k3s kubectl get pods -A
```
**Expect:** pods in `kube-system`, `ingress-nginx`, `cert-manager`,
`external-secrets` all `Running` (ebs-csi too). Do not proceed until they are.

> On k3s use `k3s kubectl` (there is no standalone `kubectl`). Run as root.

### A6. [SERVER] Confirm the images pull

```bash
sudo k3s crictl pull ghcr.io/salman-719/retailvision/eep:1.0.0
```
**Expect:** `Image is up to date` / a digest line. If you get `not found` or
`401`, finish A3 (build green + packages Public) before continuing.

### A7. [SERVER] Install the application (Helm)

First set the variables for this server session (use **your** EIP):
```bash
export EIP=34.248.161.113 OWNER=salman-719 REGION=eu-west-1 BUCKET=retailvision-prod-objects-692461731658
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
cd /opt/retail-edge
```
Then install — this is **one line**:
```bash
helm upgrade --install retailvision ./charts/retailvision -f charts/retailvision/values.production.yaml --set global.imageRegistry=ghcr.io/$OWNER/retailvision --set ingress.appHost=app.$EIP.nip.io --set eep.grpcHost=eep.$EIP.nip.io --set s3.bucket=$BUCKET --set s3.region=$REGION -n retailvision --create-namespace
```
**Expect:** `STATUS: deployed` within ~30s (no migrate hook to wait on).

### A8. [SERVER] Verify the platform is live

```bash
k3s kubectl -n retailvision get pods
```
**Expect** all `Running` / `1/1`: `postgres-0`, `redis-server-0`, `eep-…`,
`frontend-…`. (No `iep3` yet — that's per-store, Part B.)

```bash
k3s kubectl -n retailvision logs deploy/eep --tail=20
```
**Expect:** `alembic … Running upgrade … 0003`, `Application startup complete`,
`Uvicorn running on http://0.0.0.0:8000`, and `GET /health 200 OK` — **no**
Postgres/Redis errors.

```bash
curl -sk -o /dev/null -w "%{http_code}\n" "https://app.$EIP.nip.io/api/stores"
```
**Expect:** `401` (API is live and requires auth). `404` would mean the proxy
chain is wrong; `000` means the cert/ingress isn't ready yet.

### A9. [LOCAL] Open the app

Browse to **`http://app.<your-EIP>.nip.io`** (type your real IP, e.g.
`http://app.34.248.161.113.nip.io`) — the RetailVision UI loads. Register the
first user. **Cloud is done.**

> HTTPS: if the browser warns or `curl` needs `-k`, the Let's Encrypt cert for
> nip.io may be rate-limited. Switch to the internal CA (re-run A7 adding
> `--set ingress.clusterIssuer=retailvision-ca-issuer`) — functional, but the
> browser will show an untrusted-cert warning.

---

## PART B — Add a store

Do this once per store.

### B1. Create the store record and get its UUID

**[LOCAL]** In the web UI, create the store (you'll give it a name; the system
also assigns a URL **slug**, e.g. `ali-salman`). The UI does **not** show the
UUID, so retrieve it one of these ways:

**Method 1 — query the database (definitive). [SERVER]:**
```bash
k3s kubectl -n retailvision exec -it postgres-0 -- psql -U retailvision -d retailvision -c "SELECT id, name, slug, created_at FROM stores ORDER BY created_at DESC;"
```
The **`id`** column is the UUID (e.g. `3f2a…-…`). The newest row is at the top.

**Method 2 — browser DevTools. [LOCAL]:** open DevTools → **Network**, reload the
store page, click the `GET /api/store/<slug>/...` (or `GET /api/stores`) request →
**Response** → copy the `"id"` field.

> Note: store **URLs use the slug** (`/api/store/ali-salman/...`), but
> `iep3.stores` in Helm needs the **UUID** from above.

### B2. [SERVER] Start that store's IEP3 worker

Set your variables (use your EIP and the new store UUID):
```bash
export EIP=34.248.161.113 OWNER=salman-719 REGION=eu-west-1 BUCKET=retailvision-prod-objects-692461731658
export STORE=00000000-0000-0000-0000-000000000001     # the UUID from B1
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
cd /opt/retail-edge
```
Re-run Helm (one line):
```bash
helm upgrade --install retailvision ./charts/retailvision -f charts/retailvision/values.production.yaml --set global.imageRegistry=ghcr.io/$OWNER/retailvision --set ingress.appHost=app.$EIP.nip.io --set eep.grpcHost=eep.$EIP.nip.io --set s3.bucket=$BUCKET --set s3.region=$REGION --set "iep3.stores={$STORE}" -n retailvision
```

> ⚠️ **`iep3.stores` is the COMPLETE list, not an "add".** Helm makes the running
> IEP3 workers match exactly what you pass. To add a second store, pass **both**
> UUIDs — `--set "iep3.stores={uuid1,uuid2}"`. If you pass only the new one, the
> previous store's IEP3 worker is **deleted**. (Tip: keep the running set in
> `values.production.yaml` under `iep3.stores:` so you don't have to remember it.)

Verify:
```bash
k3s kubectl -n retailvision get pods -l app=iep3
```
**Expect:** one `iep3-<short>` `1/1 Running` pod **per UUID** in the list.

> Capacity: each store adds one IEP3 pod. For several stores, add nodes
> (`agent_count` in `terraform.tfvars` → `terraform apply`) or a bigger
> `server_instance_type`.

### B3. Per new store — what changes (and what doesn't)

| Step | What changes per store | What stays the same |
|---|---|---|
| Create store (UI) | new name → new **UUID** + slug | — |
| Cloud IEP3 (B2) | the **`iep3.stores` list** — pass **all** UUIDs cumulatively | `EIP`, `OWNER`, `REGION`, `BUCKET`, the rest of the command |
| Edge device (Part C) | **`STORE`** = that store's UUID; runs on **that store's** Jetson | `EIP`, `AGENT_SECRET`, GHCR creds — identical for every store |

So onboarding store N is: (1) create it → get UUID, (2) `helm upgrade` with the
**full** `iep3.stores` set including the new UUID, (3) on that store's Jetson run
Part C with only `STORE` changed.

---

## PART C — Edge device (per store, Jetson)

Prerequisite: the **cloud must already be deployed** (Part A) and the **store
created** (Part B) — you need its UUID.

### C0. Prerequisites

**On the [LOCAL] workstation** (to fetch the agent secret + CA — same tools as Part A):
- `aws` CLI v2 configured with the `adsal` profile (`aws configure set region eu-west-1 --profile adsal`)
- `terraform` (to read outputs from `infra/aws`)
- AWS Session Manager plugin (`brew install --cask session-manager-plugin`)
- this git repo cloned locally (you already have it from Part A)

**On the [EDGE] Jetson device:**
- Ubuntu with **JetPack / NVIDIA drivers** installed (the bootstrap assumes the
  GPU + container runtime are present; it installs `nvidia-container-toolkit`).
- `git` and `curl`:
  ```bash
  sudo apt-get update && sudo apt-get install -y git curl
  ```
- Network egress from the store to:
  - `eep.<your-EIP>.nip.io:50051` (gRPC to EEP) and `:6380` (server Redis, TLS)
  - `ghcr.io` (to pull edge images) and `get.k3s.io` (to install k3s)
- Root/sudo. The bootstrap installs k3s itself — you do **not** pre-install it.
- Edge images present on GHCR (`iep1`, `iep2`, `yolo`, `osnet`, `edge-agent`,
  arm64). They were built by the `v1.0.0` tag in Part A; make those packages
  **Public**, or set `GHCR_USER`/`GHCR_TOKEN` below for private pulls.

### C1. [LOCAL] Collect the inputs (agent secret + gRPC CA + store UUID)

```bash
cd ~/path/to/retail-edge/infra/aws
export AWS_PROFILE=adsal AWS_DEFAULT_REGION=eu-west-1
terraform output -raw agent_secret        # copy this — the shared secret
terraform output -raw server_public_ip    # this is your <EIP>
```
Get the gRPC CA so the edge trusts EEP — connect to the server and print it:
```bash
aws ssm start-session --target "$(terraform output -raw server_instance_id)"
```
**[SERVER]:**
```bash
sudo k3s kubectl -n cert-manager get secret retailvision-ca -o jsonpath='{.data.tls\.crt}' | base64 -d
```
Copy the entire `-----BEGIN CERTIFICATE----- … -----END CERTIFICATE-----` block;
you'll save it as `ca.crt` on the edge in C2. Type `exit` to leave the server.
Also have the store **UUID** ready (from Part B / the `psql` query).

### C2. [EDGE] Get the code and bootstrap

Clone the repo on the device:
```bash
git clone https://github.com/Salman-719/retail-edge.git
cd retail-edge
git checkout deploy/aws-k3s
```
Save the CA you copied in C1:
```bash
sudo mkdir -p /etc/retailvision/certs
sudo tee /etc/retailvision/certs/ca.crt >/dev/null   # paste the PEM block, then press Ctrl-D
```
Set variables:
```bash
export EIP=34.248.161.113                            # server Elastic IP (terraform output server_public_ip)
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
sudo -E bash scripts/bootstrap-edge-k3s.sh "$STORE" 1.0.0 "eep.$EIP.nip.io" "$AGENT_SECRET"
```
Restart the agent so it picks up the CA:
```bash
sudo systemctl restart retailvision-edge-agent
```

### C3. [EDGE] Verify

```bash
sudo k3s kubectl get pods -n retailvision
journalctl -u retailvision-edge-agent -f
```
**Expect:** `iep1-daemon`, `yolo-service`, `osnet-service` `Running`; the journal
prints `heartbeat sent store_id=<UUID>` every 30s. On the **[SERVER]**,
`k3s kubectl -n retailvision logs deploy/eep | grep <STORE-UUID>` shows it connect.
Add cameras via the UI; the Edge Agent creates per-camera IEP2 pods on demand.

---

## PART D — Updating

### D1. Update the application (new code → new image version)

1. **[LOCAL]** merge your changes into `deploy/aws-k3s`, then tag & push:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
   Wait for **Actions** to go green (images pushed as `:1.0.1`).
2. **[SERVER]** set variables, then roll out the new tag:
   ```bash
   export EIP=34.248.161.113 OWNER=salman-719 REGION=eu-west-1 BUCKET=retailvision-prod-objects-692461731658
   export STORE=00000000-0000-0000-0000-000000000001 TAG=1.0.1
   export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
   cd /opt/retail-edge && git pull
   ```
   Then (one line):
   ```bash
   helm upgrade retailvision ./charts/retailvision -f charts/retailvision/values.production.yaml --set global.imageRegistry=ghcr.io/$OWNER/retailvision --set ingress.appHost=app.$EIP.nip.io --set eep.grpcHost=eep.$EIP.nip.io --set s3.bucket=$BUCKET --set s3.region=$REGION --set "iep3.stores={$STORE}" --set eep.image.tag=$TAG --set iep3.image.tag=$TAG --set frontend.image.tag=$TAG -n retailvision
   ```
3. **[SERVER]** watch the rollout:
   ```bash
   k3s kubectl -n retailvision rollout status deploy/eep
   k3s kubectl -n retailvision get pods
   ```
   **Expect:** new pods replace old ones, all `Running`. EEP re-runs Alembic on
   start (idempotent).

> Keep a single source of truth: bump the default tags in
> `charts/retailvision/values.yaml` (`eep.image.tag`, etc.) and commit, so you
> can drop the per-tag `--set`s.

### D2. Update chart/config only (no new image)

1. **[LOCAL]** edit the chart or `values.production.yaml`, commit & push.
2. **[SERVER]** `git pull` then re-run the **A7** helm command (without
   `--create-namespace`). Helm applies only what changed.

### D3. Update infrastructure (Terraform)

1. **[LOCAL]** edit `infra/aws/*.tf` (or `terraform.tfvars`).
2. ```bash
   cd infra/aws && export AWS_PROFILE=adsal
   terraform plan      # review carefully — see what will change/replace
   terraform apply
   ```
   **Caution:** changing `server_instance_type` or the AMI **replaces the EC2
   instance** (re-bootstraps k3s and wipes in-cluster state). Adding
   `agent_count` only adds nodes (safe). Read the plan before approving.

### D4. Restart a service (no change, just bounce it)

```bash
k3s kubectl -n retailvision rollout restart deploy/eep
k3s kubectl -n retailvision rollout restart deploy/frontend
k3s kubectl -n retailvision rollout restart statefulset/redis-server
```

### D5. Update an edge device

```bash
# [EDGE] update inference services to a new image tag:
k3s kubectl -n retailvision set image deployment/yolo-service yolo-service=ghcr.io/salman-719/retailvision/yolo:1.0.1
k3s kubectl -n retailvision set image deployment/osnet-service osnet-service=ghcr.io/salman-719/retailvision/osnet:1.0.1
# IEP2 (per-camera) uses IEP2_IMAGE from the agent env; bump it then:
sudo sed -i 's#retailvision/iep2:.*#retailvision/iep2:1.0.1#' /etc/retailvision/edge-agent.env
sudo systemctl restart retailvision-edge-agent
```

---

## PART E — Troubleshooting (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `aws ... InvalidClientTokenId` | profile region not enabled (opt-in) | `aws configure set region eu-west-1 --profile adsal` |
| `SessionManagerPlugin is not found` | plugin missing | `brew install --cask session-manager-plugin` |
| zsh `command not found: --flag` | multi-line paste mangled | paste **one line** at a time |
| `helm ... namespaces "retailvision" not found` on first try | namespace race | include `--create-namespace` (step A7) |
| Pod `ImagePullBackOff` | build not green or package private | A3: build green + set `eep`/`iep3`/`frontend` **Public**; verify `k3s crictl pull` |
| Pod `Pending` "Insufficient cpu" | node too small | add `agent_count` or bigger `server_instance_type` (D3) |
| `relation "tracking_history" does not exist` | Postgres volume not freshly seeded | clean reinstall below (needs an **empty** PVC) |
| `password authentication failed` | stale Postgres volume from an earlier password | clean reinstall below |
| `redis-server-0` stuck `ContainerCreating` | cert not issued yet | wait ~1 min; check `k3s kubectl -n retailvision get certificate` |
| EEP log `Error 111 ... redis-server:6380` | Redis still starting | transient; clears once `redis-server-0` is `Running` |
| `curl /api/...` → `404` | wrong path; real routes are `/api/auth`, `/api/stores`, … | test `/api/stores` (expect `401`) |
| `certificate retailvision-app-tls` not Ready | Let's Encrypt rate-limited nip.io | re-run A7 with `--set ingress.clusterIssuer=retailvision-ca-issuer` |
| **[EDGE]** bootstrap aborts: `Packages were downgraded ... without --allow-downgrades` (nvidia-container-toolkit) | JetPack already has a newer toolkit | already fixed (script skips it if present) — `git pull` then re-run the bootstrap |
| **[EDGE]** `retailvision-edge-agent.service not found` / namespace empty | bootstrap aborted before steps 4–7 | fix the abort cause above, then re-run the bootstrap (it's idempotent) |
| **[EDGE/SERVER]** git pull: `detected dubious ownership` | repo owned by a different user | `sudo -i` (or `git config --global --add safe.directory <path>`), then pull |

### Clean reinstall (fresh database)

Postgres seeds `schema.sql` **only on an empty volume**, so a true reset must drop
the PVC. **[SERVER]:**
```bash
helm uninstall retailvision -n retailvision 2>/dev/null
k3s kubectl delete namespace retailvision --ignore-not-found --wait=true
```
Then re-run **A7**.

### Rotate a Secrets Manager value (e.g. a password)

The node can only **read** secrets, so update from **[LOCAL]**:
```bash
aws secretsmanager put-secret-value --profile adsal --region eu-west-1 --secret-id retailvision/<name> --secret-string '<new-value>'
```
Then **[SERVER]** force a re-sync and restart consumers:
```bash
k3s kubectl -n retailvision annotate externalsecret retailvision-secrets force-sync="$(date +%s)" --overwrite
k3s kubectl -n retailvision rollout restart deploy/eep
```

---

## PART F — Teardown

**[LOCAL]:**
```bash
# app:
aws ssm start-session --target $(terraform -chdir=infra/aws output -raw server_instance_id)
#   [SERVER]: helm uninstall retailvision -n retailvision ; exit
# infra:
cd infra/aws && export AWS_PROFILE=adsal && terraform destroy
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
