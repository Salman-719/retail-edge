# RetailVision — Definitive Deployment Guide (Cloud + Edge + New Store)

This is the battle-tested, end-to-end procedure used to stand up the production
stack. It captures the exact commands **and the gotchas** discovered during the
first real deployment. Follow it top to bottom.

- **Cloud**: AWS-native **k3s on EC2** (no EKS), in-cluster Postgres + Redis,
  S3 object storage, AWS Secrets Manager, single Elastic IP via k3s ServiceLB.
- **Edge**: k3s on a Jetson per store (IEP1 + GPU inference + per-camera IEP2).
- **Registry**: GitHub Container Registry (GHCR), multi-arch images.
- **No-domain mode**: public hostnames are derived from the Elastic IP via
  `nip.io` (`app.<EIP>.nip.io`, `eep.<EIP>.nip.io`).

> Reference deployment (substitute your own): account `692461731658`, region
> `eu-west-1`, owner `salman-719`, EIP `34.248.161.113`.

---

## 0. Prerequisites

On your workstation:
- `aws` CLI v2, `terraform >= 1.5`, `git`. (`helm`/`kubectl` run **on the server**.)
- The AWS Session Manager plugin (for shell access without SSH):
  ```bash
  brew install --cask session-manager-plugin
  ```
- An AWS profile with admin-ish rights. **Gotcha:** if `aws` returns
  `InvalidClientTokenId`, your profile's region is an **opt-in region that isn't
  enabled** (e.g. `eu-south-1`). Fix:
  ```bash
  aws configure set region eu-west-1 --profile <profile>
  aws sts get-caller-identity --profile <profile>   # must print an Account ID
  ```

> **Shell gotcha:** paste **one command per line**. Multi-line commands with `\`
> continuations + blank lines get mangled by zsh ("command not found").

---

## 1. Cloud deployment (k3s on EC2)

### 1.1 Build & publish images (GHCR)

From the repo, on the `deploy/aws-k3s` branch:
```bash
git tag v1.0.0
git push origin v1.0.0          # triggers .github/workflows/build-images.yml
```
- Watch **GitHub → Actions** until the build is green. The cloud needs `eep`,
  `iep3`, `frontend`; edge GPU images (`yolo`, `osnet`) are arm64-only and may
  fail under emulation — that's fine for cloud.
- **Make the packages public**: GitHub → repo → **Packages** → for `eep`,
  `iep3`, `frontend` set visibility to **Public** (so k3s pulls without creds).
  Confirm on the server later with:
  `sudo k3s crictl pull ghcr.io/<owner>/retailvision/eep:1.0.0`

### 1.2 Provision infrastructure (Terraform)

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```
Edit `terraform.tfvars`: `aws_region`, `letsencrypt_email`, a globally-unique
`s3_bucket_name`, `git_repo_url` (must be **public** so the server can clone it),
`git_branch`. Leave `app_host`/`eep_host` empty for nip.io mode.

```bash
terraform init
terraform apply        # review, type: yes   (do NOT paste a trailing comment)
```
Note the outputs:
```bash
terraform output server_public_ip      # the Elastic IP
terraform output app_host              # app.<EIP>.nip.io
terraform output eep_host              # eep.<EIP>.nip.io
terraform output helm_install_hint     # ready-to-run helm command
terraform output -raw agent_secret     # needed for edge devices (sensitive)
```
Terraform also generates the DB/JWT/agent passwords + S3 IAM keys and writes them
to **AWS Secrets Manager** (`retailvision/*`).

### 1.3 Access the server (SSM, no SSH)

```bash
aws ssm start-session --target $(terraform output -raw server_instance_id)
```
The server's user-data clones the repo and runs `scripts/bootstrap-cloud-k3s.sh`
(k3s + ingress-nginx + cert-manager + external-secrets + ebs-csi). Confirm:
```bash
sudo tail -n 20 /var/log/cloud-init-output.log     # expect "cloud k3s bootstrap complete"
sudo k3s kubectl get pods -A                        # add-ons all Running
```
> On k3s use `k3s kubectl` (there is no standalone `kubectl`). Run as root.

### 1.4 Install the app (Helm)

Run **on the server** (the k3s API isn't exposed publicly). Use the
`helm_install_hint` output, or:
```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
cd /opt/retail-edge
helm upgrade --install retailvision ./charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --set global.imageRegistry=ghcr.io/<owner>/retailvision \
  --set ingress.appHost=app.<EIP>.nip.io \
  --set eep.grpcHost=eep.<EIP>.nip.io \
  --set s3.bucket=<your-bucket> \
  --set s3.region=<region> \
  -n retailvision --create-namespace
```
The production profile is **lean** (single replicas, no pgbouncer, direct-to-
Postgres) to fit a 2-vCPU node. Postgres is seeded from `schema.sql` via initdb;
EEP runs Alembic at startup.

### 1.5 Verify

```bash
k3s kubectl -n retailvision get pods
```
Expected `Running`: `postgres-0`, `redis-server-0`, `eep-…`, `frontend-…`
(`iep3` appears only after you add a store).

```bash
k3s kubectl -n retailvision logs deploy/eep --tail=20      # alembic ok, uvicorn on :8000, no redis errors
curl -sk -o /dev/null -w "%{http_code}\n" https://app.<EIP>.nip.io/api/stores   # 401 = API live (not 404)
curl -sk https://app.<EIP>.nip.io/ | head -3               # SPA HTML
```
Open **http://app.<EIP>.nip.io** in a browser.

---

## 2. Add a new store

A store is the unit of tenancy. Each store gets its own IEP3 reconciliation
worker and (optionally) an edge device.

### 2.1 Create the store record

Register/log in on the web UI and create the store, **or** via the API
(`POST /api/stores` — see `RetailVision-Phase*.postman_collection.json`). Note
the returned **store UUID**.

### 2.2 Bring up the store's IEP3 worker

Append the UUID to `iep3.stores` and re-run Helm (keep all the same `--set`s):
```bash
helm upgrade --install retailvision ./charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --set global.imageRegistry=ghcr.io/<owner>/retailvision \
  --set ingress.appHost=app.<EIP>.nip.io \
  --set eep.grpcHost=eep.<EIP>.nip.io \
  --set s3.bucket=<your-bucket> --set s3.region=<region> \
  --set "iep3.stores={<STORE_UUID_1>,<STORE_UUID_2>}" \
  -n retailvision
```
Verify: `k3s kubectl -n retailvision get pods -l app=iep3` → `iep3-<short>` Running.

> For more than a couple of stores, raise node capacity: set `agent_count` in
> `terraform.tfvars` and `terraform apply` (agents auto-join), or use a larger
> `server_instance_type`.

---

## 3. Edge deployment (per store, Jetson)

### 3.1 Gather inputs (on your workstation)

```bash
cd infra/aws
terraform output -raw agent_secret           # shared secret
# Export the gRPC CA so the edge trusts EEP:
aws ssm start-session --target $(terraform output -raw server_instance_id)
#   on the server:
sudo k3s kubectl -n cert-manager get secret retailvision-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ca.crt
#   copy ca.crt off the server (scp via SSM / paste) to the Jetson
```
You also need the **store UUID** (from §2.1).

### 3.2 Bootstrap the Jetson

On the device, from a clone of the repo (public branch):
```bash
# Optional, only if GHCR packages are private:
export GHCR_USER=<github-user> GHCR_TOKEN=<PAT with read:packages>

sudo -E bash scripts/bootstrap-edge-k3s.sh \
  <STORE_UUID> 1.0.0 eep.<EIP>.nip.io <agent_secret>
```
This installs k3s (API on loopback only), the NVIDIA device plugin, IPC paths,
the edge manifests (IEP1 + YOLO + OSNet), and the Edge Agent systemd service.
Then drop in the CA and restart the agent:
```bash
sudo cp ca.crt /etc/retailvision/certs/ca.crt
sudo systemctl restart retailvision-edge-agent
```

### 3.3 Verify

```bash
k3s kubectl get pods -n retailvision           # iep1-daemon, yolo-service, osnet-service Running
journalctl -u retailvision-edge-agent -f       # "heartbeat sent store_id=..." every 30s
```
On the cloud: `k3s kubectl -n retailvision logs deploy/eep | grep <STORE_UUID>`
should show the agent connecting. Add cameras via the UI/API; the Edge Agent
creates a per-camera IEP2 deployment on demand.

---

## 4. Day-2 operations & troubleshooting

These are the exact issues hit during the first deploy and how to resolve them.

| Symptom | Cause | Fix |
|---|---|---|
| `aws ... InvalidClientTokenId` | profile region is a non-enabled opt-in region | `aws configure set region eu-west-1 --profile <p>` |
| `SessionManagerPlugin is not found` | plugin missing | `brew install --cask session-manager-plugin` |
| zsh `command not found: --flag` | multi-line paste mangled | paste one line at a time |
| `Namespace ... cannot be imported ... missing key managed-by` | `--create-namespace` collided with a chart-managed namespace | (already fixed: chart no longer ships namespace.yaml) wipe ns + reinstall |
| Pod `ImagePullBackOff` (eep/iep3/frontend) | GHCR build not green or packages private | make packages **Public**; verify `k3s crictl pull …` |
| Pod `Pending` "Insufficient cpu" | node too small | lean profile already applied; or `agent_count`>0 / bigger instance |
| `relation "tracking_history" does not exist` | Postgres not seeded with `schema.sql` | (fixed) initdb ConfigMap seeds it; needs a **fresh** PVC — see reset below |
| `password authentication failed for user retailvision` | alembic used the dev default password | (fixed) `ALEMBIC_DATABASE_URL` set on EEP |
| `redis-server-0` stuck `ContainerCreating` | missing `redis-server-tls` secret | (fixed) chart issues a Redis cert via the internal CA |
| EEP `Error 111 / TLS` to redis | client verified private CA | (fixed) `redis-url` uses `?ssl_cert_reqs=none` |
| `certificate retailvision-app-tls` not Ready | Let's Encrypt rate-limited nip.io | re-run helm with `--set ingress.clusterIssuer=retailvision-ca-issuer` |

### Clean reinstall (when you need a fresh DB)

Postgres only runs `schema.sql` on an **empty** volume, so a full reset must drop
the PVC:
```bash
helm uninstall retailvision -n retailvision 2>/dev/null
k3s kubectl delete namespace retailvision --ignore-not-found --wait=true
# then re-run the helm upgrade --install from §1.4 (--create-namespace)
```

### Rotate a secret (e.g. redis-url)

The node role can only **read** Secrets Manager, so update from your workstation:
```bash
aws secretsmanager put-secret-value --profile <p> --region <region> \
  --secret-id retailvision/redis-url \
  --secret-string 'rediss://redis-server:6380?ssl_cert_reqs=none'
# force re-sync + restart consumers (on the server):
k3s kubectl -n retailvision annotate externalsecret retailvision-secrets \
  force-sync="$(date +%s)" --overwrite
k3s kubectl -n retailvision rollout restart deploy/eep
```

### Update images (new version)

```bash
git tag v1.0.1 && git push origin v1.0.1            # build
helm upgrade retailvision ... --set eep.image.tag=1.0.1 --set iep3.image.tag=1.0.1 \
  --set frontend.image.tag=1.0.1 -n retailvision    # roll out
```

---

## 5. Teardown

```bash
# app
helm uninstall retailvision -n retailvision
# infra
cd infra/aws && terraform destroy
```
> S3 buckets and gp3 PVC volumes use Retain/versioning — empty/delete them
> manually if you want them fully gone. Released EBS volumes from prior installs
> may linger; remove them in the EC2 console to stop charges.

---

## Appendix — what the chart does for you (so you don't have to)

- Seeds Postgres from `schema.sql` (initdb ConfigMap); EEP self-migrates (Alembic).
- Direct EEP/IEP3 → Postgres (pgbouncer optional, off in production).
- Redis TLS via internal-CA cert; clients use `ssl_cert_reqs=none`.
- External Secrets syncs `retailvision/*` from AWS Secrets Manager using the node
  IAM role (no static keys for that path; S3 uses a dedicated IAM user's keys).
- cert-manager issues the public ingress cert (LE) and the edge↔EEP gRPC cert
  (internal CA).
