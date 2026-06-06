# Deploy — AWS Cloud (k3s on EC2)

End-to-end runbook for the RetailVision **cloud** plane. AWS-native, **no EKS**:
a k3s cluster on EC2 that scales by adding agent nodes and a per-store IEP3
StatefulSet. Cost-efficient by design — in-cluster Postgres/Redis, S3 object
storage, AWS Secrets Manager, and a single Elastic IP fronting ingress + gRPC via
k3s ServiceLB (no always-on NLB).

For the edge (per-store Jetson) side, see [deploy-edge.md](deploy-edge.md).

---

## Architecture

```
                          AWS account / region
  ┌──────────────────────────────────────────────────────────────┐
  │ VPC (public subnets, 2 AZ)                                     │
  │   EC2 k3s server (Graviton t4g)  ── Elastic IP ── DNS          │
  │     ServiceLB (klipper): :443 ingress-nginx, :50051 eep-grpc   │
  │     ┌─ EEP (Deployment + HPA)                                  │
  │     ├─ IEP3 (StatefulSet per store)                            │
  │     ├─ frontend (nginx SPA, /api -> eep-http)                  │
  │     ├─ pgbouncer -> Postgres (StatefulSet, EBS gp3)            │
  │     ├─ Redis (StatefulSet, EBS gp3, TLS)                       │
  │     ├─ cert-manager (LE public cert + internal CA for gRPC)    │
  │     └─ External Secrets <- AWS Secrets Manager (node IAM role) │
  │   [+ optional k3s agent nodes for scale-out]                   │
  │   S3 bucket (object storage)                                   │
  └──────────────────────────────────────────────────────────────┘
```

## Prerequisites

- AWS account + credentials with permissions for EC2/VPC/IAM/S3/SecretsManager/Route53.
- Tools locally: `terraform >= 1.5`, `helm 3`, `kubectl`, `aws` CLI.
- A domain you control for `app.<domain>` (SPA/API) and `eep.<domain>` (edge gRPC).
- Images pushed to GHCR (see [GHCR images](#0-build--push-images-ghcr)).
- The cluster add-ons are installed automatically by `scripts/bootstrap-cloud-k3s.sh`
  (run from EC2 user-data): ingress-nginx, cert-manager (+ ClusterIssuers),
  external-secrets (+ `aws-secrets-manager` ClusterSecretStore), aws-ebs-csi-driver.

## Cost (rough, us-east-1, single node)

| Item | Approx /mo |
|------|-----------|
| 1× `t4g.large` EC2 (on-demand) | ~$49 (≈$30 with a 1-yr saving plan) |
| EBS gp3 (root 40Gi + PVCs ~70Gi) | ~$9 |
| Elastic IP (attached) | $0 |
| S3 + Secrets Manager | a few $ |
| **Total** | **~$60/mo** (no EKS fee, no NLB) |

Scale-out: each agent node adds one EC2 charge; each store adds one IEP3 pod.

---

## 0. Build & push images (GHCR)

Tag a release (or run the workflow manually) to build all images multi-arch and
push to `ghcr.io/<owner>/retailvision/<service>:<tag>`:

```bash
git tag v1.0.0 && git push origin v1.0.0      # triggers .github/workflows/build-images.yml
```

Make the packages public, **or** keep them private and provide pull credentials
(node `registries.yaml` on edge; on cloud the k3s server pulls with its own
`registries.yaml` if you add one). Set `global.imageRegistry=ghcr.io/<owner>/retailvision`
in Helm values.

## 1. Provision infrastructure (Terraform)

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# Edit: aws_region, app_host, eep_host, letsencrypt_email, s3_bucket_name,
#       git_repo_url/git_branch, server_instance_type, agent_count.
terraform init
terraform apply
```

Outputs:
- `server_public_ip` — the Elastic IP. Point DNS here.
- `server_instance_id` — for SSM (`aws ssm start-session --target <id>`).
- `agent_secret` — shared secret for edge devices (`terraform output -raw agent_secret`).

Terraform also seeds AWS Secrets Manager with generated passwords + the S3 IAM
user keys (see [Secrets](#secrets-mapping)).

## 2. DNS

Create A records (or set `create_dns_records=true` + `route53_zone_id` to let
Terraform do it):

```
A  app.<domain>  -> <server_public_ip>
A  eep.<domain>  -> <server_public_ip>
```

## 3. Wait for the cluster to come up

The server's user-data runs `scripts/bootstrap-cloud-k3s.sh` (k3s + add-ons).
Watch via SSM:

```bash
aws ssm start-session --target <server_instance_id>
sudo tail -f /var/log/cloud-init-output.log      # bootstrap progress
sudo kubectl get pods -A                          # add-ons Running
```

Fetch the kubeconfig to your laptop and rewrite the server address:

```bash
aws ssm start-session --target <id> \
  --document-name AWS-StartPortForwardingSession ...   # or scp /etc/rancher/k3s/k3s.yaml
# replace 127.0.0.1 with the EIP, save as ~/.kube/retailvision
export KUBECONFIG=~/.kube/retailvision
```

## 4. Deploy the app (Helm)

```bash
helm upgrade --install retailvision ./charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --set global.imageRegistry=ghcr.io/<owner>/retailvision \
  --set ingress.appHost=app.<domain> \
  --set eep.grpcHost=eep.<domain> \
  --set s3.bucket=<your-bucket> --set s3.region=<region> \
  --set "iep3.stores={<store-uuid>}" \
  --namespace retailvision --create-namespace

kubectl -n retailvision rollout status deployment/eep --timeout=180s
kubectl -n retailvision get pods
```

The `eep-migrate` pre-install hook runs Alembic against Postgres before EEP starts.
cert-manager issues the public cert (LE http-01) and the internal gRPC cert.

## 5. Export the gRPC CA for edge devices

Edge devices must trust EEP's gRPC cert (signed by the internal CA):

```bash
kubectl -n cert-manager get secret retailvision-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ca.crt
# copy ca.crt to /etc/retailvision/certs/ca.crt on each edge device
```

## 6. Onboard a store's edge device

On the Jetson, with the `agent_secret` from Terraform:

```bash
sudo bash scripts/bootstrap-edge-k3s.sh <store_uuid> 1.0.0 eep.<domain> <agent_secret>
```

See [deploy-edge.md](deploy-edge.md) for details.

## 7. Verify end-to-end

```bash
curl -fsS https://app.<domain>/api/health        # EEP via ingress -> frontend proxy
kubectl -n retailvision get pods                  # eep, iep3-<store>, postgres, redis, pgbouncer, frontend
kubectl -n retailvision logs deploy/eep | tail    # agent heartbeats arriving
```

---

## Secrets mapping

External Secrets syncs AWS Secrets Manager → the `retailvision-secrets` k8s Secret.
Names are set in `infra/aws/variables.tf` (`secret_names`) and must match
`charts/retailvision/values.yaml` (`secrets.*`).

| Secrets Manager name | k8s key | Used by | Set by |
|----------------------|---------|---------|--------|
| `retailvision/postgres-password` | `postgres-password` | postgres, pgbouncer, eep, iep3, migrate | Terraform (generated) |
| `retailvision/redis-url` | `redis-url` | eep, iep3 | Terraform (`rediss://redis-server:6380`) |
| `retailvision/redis-password` | `redis-password` | (reserved) | Terraform (generated) |
| `retailvision/jwt-secret` | `jwt-secret` | eep | Terraform (generated) |
| `retailvision/agent-secret` | `agent-secret` | eep ↔ edge | Terraform (generated) |
| `retailvision/s3-access-key` | `s3-access-key` | eep | Terraform (S3 IAM user) |
| `retailvision/s3-secret-key` | `s3-secret-key` | eep | Terraform (S3 IAM user) |

To rotate: update the secret in Secrets Manager; External Secrets re-syncs within
`refreshInterval` (1h). Terraform `ignore_changes` keeps it from clobbering rotations.

> S3 note: EEP requires explicit S3 keys (`services/eep/app/core/config.py`), so a
> dedicated IAM user is provisioned for it. The EBS CSI driver and External Secrets
> themselves use the **node instance-profile role** (no static keys).

## Scale-out

- **More stores:** append the UUID to `iep3.stores` and `helm upgrade` (new IEP3
  StatefulSet), then bootstrap that store's edge device.
- **More capacity:** set `agent_count` > 0 in `terraform.tfvars` and `apply`; agents
  join automatically with the shared k3s token. EEP scales via its HPA.
- **HA upgrade:** when you outgrow a single node, front the nodes with an AWS NLB
  (target the ingress + 50051 NodePorts) and run multiple k3s servers with an
  external datastore — out of scope for this single-node cost-optimized baseline.

## Teardown

```bash
helm -n retailvision uninstall retailvision
cd infra/aws && terraform destroy
```

> S3 bucket and gp3 PVC volumes use `Retain`/versioning — empty/delete them
> manually if you want them gone.
