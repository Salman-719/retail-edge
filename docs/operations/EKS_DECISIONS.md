# RetailVision Cloud — EKS Deployment Decision Record

A detailed rationale for **every deployment decision** in the cloud (Amazon EKS)
tier: what was chosen, **why**, and **why the alternatives were rejected** — plus how
components communicate, how the system scales, and what it costs.

Scope: the `deploy/aws-eks` branch (`infra/aws/` + `charts/retailvision/`). For the
concise topology reference see [`EKS_ARCHITECTURE.md`](EKS_ARCHITECTURE.md); for
step-by-step install see [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md). The **edge**
tier stays on k3s (Jetson per store) and is out of scope except where it talks to the
cloud.

---

## 1. TL;DR topology

```
                         Internet
                            │
        ┌───────────────────┴──────────────────────────────┐
   Ingress NLB (2 EIPs)                      EEP gRPC NLB (2 EIPs)
   app.<eip>.nip.io :443                     eep.<eip>.nip.io :50051 (mTLS)
        │                                         │
   ingress-nginx ──► frontend ──/api──► eep-http  │ (TLS terminated at EEP pod)
     (cert-manager) └──/agent──► iep6              │
                                                   ▼
   ┌──────────────────────── EKS (managed control plane) ───────────────────────────┐
   │ STABLE pool  (on-demand 2×t4g.large, 2 AZ, TAINT stable=true:NoSchedule)         │
   │   system:  coredns·kube-proxy·vpc-cni·ebs-csi·pod-identity-agent                  │
   │   ctrls:   aws-lb-controller·ingress-nginx·cert-manager·ESO·metrics-server·KEDA·karpenter│
   │   stateful: postgres(TimescaleDB)·redis·prometheus·grafana·mlflow·pgbouncer       │
   │ KARPENTER pool (Graviton arm64, Spot+on-demand fallback, consolidates)            │
   │   workers: eep·iep3/iep4(per store)·iep5(jobs)·iep6-agent·frontend                │
   └───────────────────────────────────────────────────────────────────────────────────┘
       EBS gp3 (PVCs)   S3 + gateway endpoint   Secrets Manager (via External Secrets)

 edge k3s ── WireGuard(EIP, SSM-managed) ── internal NLBs ── Postgres:5432 / Redis:6380
```

EEP is the control plane: it **provisions per-store workers through the Kubernetes
API**, and Karpenter supplies nodes to fit them. A taint isolates the stable pool so
Spot churn never touches the data/control tier.

---

## 2. Cluster — why Amazon EKS

**Chosen:** Amazon EKS (managed, multi-AZ control plane).
**Why:** the prior design was a single k3s server on one EC2 — a SPOF with no HA
control plane and only manual scaling. EKS gives an AWS-managed control plane, native
IAM (IRSA / Pod Identity), and first-class autoscaling. The app is already vanilla
Kubernetes, so it migrates almost unchanged.

| Rejected | Why |
|---|---|
| Keep k3s on EC2 | Single control-plane node = SPOF; manual scaling; you run etcd/upgrades. The thing we're leaving. |
| Self-managed k8s (kubeadm) | No control-plane fee but you own HA masters, etcd backups, upgrades, cert rotation — big ops cost, no functional gain. |
| ECS / Fargate | EEP provisions workers via the **Kubernetes API** (`iep3/iep4/iep5_manager` create StatefulSets/Jobs). Porting to ECS task APIs means rewriting the orchestration core; Fargate per-pod pricing is poor for many small per-store daemons. |
| EKS Auto Mode | Less control over a tuned Spot/Graviton + tainted-stable-pool layout; we want explicit NodePool/taint control. |

---

## 3. Networking

### 3.1 Public subnets, **no NAT gateway**
Nodes run in 2 public subnets (2 AZs) with public IPs; egress via the Internet
Gateway. A **free S3 gateway endpoint** keeps S3 traffic off the public path.

- **Why:** reliable egress (GHCR pulls, AWS APIs) without paying for a NAT gateway
  (~\$32/mo/AZ + per-GB). Same egress model the prior k3s box used — known-good.
- **Security:** node SG allows only intra-cluster traffic + what the NLBs forward;
  EKS API is the admin entry (optionally CIDR-locked via `eks_public_access_cidrs`);
  SSM instead of SSH.
- **Rejected — private subnets + NAT** (textbook EKS): more secure-by-default but adds
  a NAT gateway (cost + managed dependency) for egress we already get reliably. Per
  the explicit guidance: *if it works reliably without NAT, don't use it.*

### 3.2 Public and private NLBs
- **Ingress NLB** (2 EIPs) → `ingress-nginx` → HTTPS app/API.
- **gRPC NLB** (2 EIPs) → `eep-grpc` Service → edge↔EEP **mTLS** on `:50051` (TLS
  terminates at the EEP pod).
- **Postgres internal NLB** → `postgres` Service on `:5432`.
- **Redis internal NLB** → `redis-server` Service on TLS `:6380`.

- **Why separate:** gRPC is **L4 mTLS passthrough** — the LB must *not* terminate TLS
  (EEP verifies the client cert). App traffic is **L7** and wants ingress-nginx path
  routing (`/api`→eep, `/agent`→iep6) + cert-manager TLS. A dedicated gRPC LB gives
  edge devices a stable, isolated endpoint that scales/operates independently of app
  traffic.
- **Why NLB not ALB:** ALB is HTTP(S)-only — no raw TCP/mTLS passthrough for gRPC; NLB
  is L4, cheaper per-LCU, and supports **static EIPs** (needed for nip.io).
- **Why EIPs:** `nip.io` is IP-based DNS; NLBs otherwise get rotating DNS names.
  Pinned EIPs give stable hostnames with no real domain.
- **Rejected:** one shared NLB (gRPC via ingress-nginx TCP passthrough) — saves a LB
  but couples edge gRPC to the app ingress and complicates certs; klipper/ServiceLB —
  k3s-only, unavailable on EKS.

The two data NLBs have private addresses only. They are reached through a small
WireGuard EC2 gateway that has no SSH ingress and is managed with AWS Systems
Manager. The gateway SNATs enrolled `10.99.0.0/24` peers into the VPC, so the
existing VPC route tables do not need a route per store. The instance ignores
automatic AMI drift because its server key and enrolled peer set live on the
encrypted root volume; replace it only during a planned edge re-enrollment.

### 3.3 DNS
`nip.io` off the EIPs by default (no domain). `create_dns_records=true` +
`route53_zone_id` switches to Route53 A-records (`app_host`→ingress EIP,
`eep_host`→gRPC EIP) for production.

---

## 4. Compute — two node pools

### 4.1 Stable on-demand pool (tainted)
EKS-managed node group: `2× t4g.large` Graviton, on-demand, 2 AZs, **labeled
`workload=stable` + tainted `stable=true:NoSchedule`**, `max 4` for manual headroom.

- **Why on-demand + tainted:** hosts everything that must not be disrupted —
  TimescaleDB, Redis, monitoring, MLflow, and all controllers. The taint repels
  everything by default; only pods that **tolerate** it land here, so Spot reclaim or
  Karpenter consolidation can never evict the database or a controller.
- **How workloads opt in:** every system add-on sets `nodeSelector: workload=stable`
  + the toleration in `infra/aws/*.tf`; the chart's stateful pods get the same via
  `stablePool.nodeSelector` + `stablePool.tolerations` (`values.production.yaml`).
- **Why 2 / max 4:** 2 = HA across 2 AZs; `max 4` = manual growth room. Not
  autoscaled (Karpenter owns elasticity).

### 4.2 Karpenter elastic pool
Graviton arm64, capacity `["spot","on-demand"]` (Spot first), families `t/m/c` gen>6,
AL2023, `consolidationPolicy: WhenEmptyOrUnderutilized` after 1 min, capped at
`karpenter_cpu_limit` (200 vCPU).

- **Why Karpenter (not Cluster Autoscaler):** provisions **right-sized** nodes from
  pending-pod shape in seconds (no per-shape ASGs), bin-packs, mixes Spot/on-demand,
  and **consolidates** idle nodes — ideal for the bursty per-store pattern (activate a
  store → new IEP3+IEP4; close a shift → IEP5 Job). CA needs one ASG per shape and is
  slower.
- **Why Spot + on-demand fallback:** workers are restartable → Spot saves ~60–70%;
  fallback keeps them schedulable when Spot is scarce.
- **Why Graviton/arm64:** images are multi-arch; arm64 ~20% cheaper at equal perf;
  one arch keeps scheduling simple.
- **Why a vCPU cap:** hard cost guardrail against runaway scale-out.
- **Rejected:** a single mixed pool (DB + workers) — Spot churn risks the DB and
  co-locating bursty workers with the DB hurts tail latency. The split is the core
  cost/performance balance.

---

## 5. Identity & secrets

| Concern | Decision | Why |
|---|---|---|
| Controller AWS perms | **IRSA** (OIDC) for EBS CSI, LB controller, External Secrets | Per-controller least-privilege roles by service account; no broad shared node role. |
| Karpenter perms | **EKS Pod Identity** (+ pod-identity-agent addon) | Current recommended mechanism; simpler association for the Karpenter submodule. |
| Secrets delivery | **External Secrets Operator → Secrets Manager** (`ClusterSecretStore`, IRSA read of `retailvision/*`) | Secrets are rotatable/audited in Secrets Manager; ESO syncs to a k8s Secret. No plaintext in Git. |
| EEP/MLflow S3 | **Static IAM user keys** (in Secrets Manager) | EEP `config.py` requires explicit S3 keys; keeps the dedicated, bucket-scoped S3 user, no app change. (IRSA for EEP = future cleanup.) |

---

## 6. Data tier — in-cluster TimescaleDB + Redis

PostgreSQL = **TimescaleDB** (`2.14.2-pg16`) and Redis run as **StatefulSets on the
stable pool**, on **EBS gp3** (default SC, `WaitForFirstConsumer`, encrypted).

- **Why in-cluster:** the analytics pipeline depends on TimescaleDB **community
  features** — hypertables + continuous aggregates (Alembic `0010`, consumed by IEP5).
  In-cluster preserves them at lowest cost with no third party.
- **Why on the stable pool:** EBS is AZ-bound and a DB must never be evicted — the
  on-demand tainted pool guarantees that. `WaitForFirstConsumer` binds the volume in
  the pod's AZ (no cross-AZ attach failures).

| Rejected | Why |
|---|---|
| RDS PostgreSQL | Ships only the Apache-2 TimescaleDB subset — no continuous aggregates/compression that `0010`/IEP5 use. Would force an analytics rewrite. |
| Timescale Cloud | Full features but third-party vendor + extra cost/egress; unneeded at this scale. |
| ElastiCache | Redis is a Stream bus tightly coupled to the pipeline; in-cluster is simpler and free of cross-service latency. Revisit at high scale. |

---

## 7. Application provisioning — why EEP drives Kubernetes

EEP is API/gRPC server **and** control plane: on store-version activation it calls the
k8s API to create that store's **IEP3** (reconciliation StatefulSet) and **IEP4**
(alert StatefulSet); on shift close it creates an **IEP5** Job. Gated by the
`eep-pipeline-manager` Role (statefulsets/services/jobs/pods) on the `eep`
ServiceAccount.

- **Why dynamic (not static Helm per store):** stores come and go; encoding each in
  Helm means a release per store. EEP-managed lifecycle keeps it in the product, and
  Karpenter supplies the nodes automatically. Escape hatch:
  `iep3.staticProvisioning=true`.
- **Placement:** these workers carry **no** stable toleration, so the taint pushes
  them onto Karpenter nodes — where elastic capacity lives.

---

## 8. Component communication

| From → To | Channel | Exposure |
|---|---|---|
| Browser → SPA/API | HTTPS 443 | Ingress NLB → ingress-nginx → `frontend`; `/api`→`eep-http`, `/api/.../agent`→`iep6` |
| Edge Agent → EEP | gRPC **mTLS** 50051 | gRPC NLB → `eep-grpc` (TLS at pod); cert from `retailvision-ca-issuer`, CA shipped to edge |
| EEP → Kubernetes API | HTTPS in-cluster | `eep` SA + RBAC; creates IEP3/IEP4 StatefulSets, IEP5 Jobs |
| EEP/IEP3/4/5/6 → Postgres | TCP 5432 (cluster Service) | **internal only** |
| Edge IEP2 → Postgres | TCP 5432 | WireGuard → internal NLB; direct writes preserve the `reconfig-edge` contract |
| EEP/IEP3 → Redis | TCP TLS (cluster Service) | **internal only** |
| Edge IEP2 → Redis | TCP TLS 6380 | WireGuard → internal NLB; publishes `batch_complete` |
| IEP4 → SMTP / IEP6 → OpenAI | 587 / HTTPS | egress via IGW; creds from Secrets Manager |
| any pod → S3 | HTTPS | via **S3 gateway endpoint** |
| ESO → Secrets Manager | HTTPS | IRSA-scoped read of `retailvision/*` |
| Prometheus → targets | HTTP `/metrics` | scrapes IEP3 `:9300` (pod annotations) + exporters |

**Key:** the data tier is not internet-exposed. EEP control uses the public mTLS
gRPC endpoint; IEP2 data uses the private WireGuard route and internal NLBs.
High-frequency frames remain in the edge-local `redis-edge`/tmpfs path.

---

## 9. Scaling model

**Three independent layers:**
1. **Pods (HPA + metrics-server):** EEP and frontend scale on CPU. Per-store
   workers scale by **count** — one IEP3 + one IEP4 per active store, one IEP5
   Job per shift close.
2. **Pods (KEDA + Prometheus):** `iep6-agent` scales on
   `http_requests_inprogress{job="iep6-agent"}` because agent work is mostly
   OpenAI/API I/O wait. `iep6-scheduler` is a singleton and is never autoscaled.
3. **Nodes (Karpenter):** launches right-sized Graviton Spot nodes for Pending pods in
   ~1 min; consolidates when idle; capped at `karpenter_cpu_limit`.

**Automatic:** more stores (→ more IEP3/IEP4 → Karpenter nodes), shift bursts (IEP5
Jobs), API load (EEP HPA). **Fixed by design:** the stable pool (2 nodes, manual
`max 4`) so the data/control tier stays predictable. N stores ≈ N×(IEP3+IEP4) pods,
bin-packed on Spot; deactivating a store deletes its workers and Karpenter
consolidates the freed node.

---

## 10. Cost (eu-west-1, idle/low load)

| Item | Qty | ~USD/mo |
|---|---|---|
| EKS control plane | 1 | ~73 |
| Stable nodes `t4g.large` on-demand | 2 | ~98 |
| Public NLBs (ingress + gRPC) | 2 | ~32 + LCU |
| Internal NLBs (Postgres + Redis) | 2 | ~32 + LCU |
| WireGuard gateway `t4g.nano` | 1 | ~3–4 |
| Elastic IPs (attached) | 4 | ~0 |
| EBS gp3 (PVCs + roots) | — | ~15–30 |
| S3 + gateway endpoint | — | usage; endpoint free |
| **NAT gateway** | **0** | **avoided (~32+ saved)** |
| Karpenter Spot workers | elastic | scales with stores; ~0 idle |
| **Idle total** | | **≈ \$265–310/mo** |

**Levers:** Spot workers (~60–70% cheaper), Graviton everywhere (~20%), no NAT,
`karpenter_cpu_limit` ceiling, `consolidateAfter=1m`, or trim to 1 stable node / 1 NLB
for dev. **Why > the ~\$130/mo single k3s box:** the ~\$100/mo delta buys a managed HA
control plane, multi-AZ stateful HA, and true elasticity — the deliberate
functionality/performance tradeoff.

---

## 11. Tooling & ops notes

- **Vendored / git-pinned modules:** the EKS module is vendored at
  `infra/aws/modules/eks` (+ `modules/karpenter`); VPC/IAM modules are pinned via
  `git::…?ref=`. This lets `terraform init` work from environments without Terraform
  **module-registry** access (e.g. AWS CloudShell, or geo-blocked `releases.hashicorp`)
  and pins exact versions.
- **Provider auth:** `kubernetes`/`helm`/`kubectl` providers use the `aws eks
  get-token` exec plugin (no long-lived kubeconfig token).
- **Two-phase apply:** the Helm/kubectl providers need the cluster first — apply
  `module.eks` (+ VPC) before the add-ons/Karpenter manifests if a provider race
  occurs.
- **Cross-node pod connectivity:** the node SG has an explicit "allow all between
  nodes" self-rule so e.g. ingress-nginx→frontend:80 works (the module default self
  rule starts at 1025 and would block port 80).
- **CloudShell state:** keep the repo + Terraform state under `$HOME` (persisted), not
  `/root` (ephemeral backing machine).

---

## 12. Decisions at a glance

| Area | Chosen | Rejected (why) |
|---|---|---|
| Control plane | EKS | k3s (SPOF), self-managed (ops), ECS/Fargate (k8s-API model) |
| Node autoscaling | Karpenter | Cluster Autoscaler (slower, per-shape ASGs) |
| Workers | Graviton Spot + on-demand fallback | all on-demand (cost), x86 (pricier) |
| Stable tier | on-demand, tainted, 2×t4g.large | mixed pool (DB at risk from Spot) |
| Egress | public subnets + IGW + S3 endpoint | private subnets + NAT (cost) |
| App ingress | NLB + ingress-nginx + cert-manager | ALB (no L4 mTLS) |
| Edge gRPC | dedicated NLB + EIPs, mTLS passthrough | shared NLB / ALB / klipper |
| Database | in-cluster TimescaleDB on EBS gp3 | RDS (no caggs), Timescale Cloud (vendor) |
| Cache/bus | in-cluster Redis | ElastiCache (coupling/cost) |
| Worker lifecycle | EEP dynamic via k8s API | static Helm-per-store |
| Secrets | ESO + Secrets Manager (IRSA) | plaintext values / node-role-only |
