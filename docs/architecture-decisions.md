# Architecture Decision Record — RetailVision Edge

## Context

RetailVision is a retail analytics platform that runs computer vision at the edge (camera-attached Jetson devices) and reconciles identities in the cloud. This document explains the key architectural decisions, the alternatives considered, and why each choice was made.

---

## ADR-001 — Edge/cloud split: detection on device, reconciliation in cloud

**Decision:** YOLO detection, BoT-SORT tracking, and per-camera ReID (IEP2) run on the Jetson Orin Nano at the store. Cross-camera identity reconciliation (IEP3) runs in the cloud.

**Why:** Detection at 2fps per camera requires ~50ms of GPU inference per frame. Running this on a cloud GPU instance per store would cost $300–800/month/store. The Orin Nano handles 3–4 cameras at $500 hardware cost, amortized over years. Cloud GPUs are reserved for cross-camera reasoning (IEP3) which is CPU-bound matrix operations on already-extracted embeddings — no GPU needed.

**Rejected alternative:** All processing in cloud. Prohibitively expensive at scale and adds 150–300ms of network latency before inference even starts, making any live feedback impossible.

---

## ADR-002 — HTTP from edge to cloud, no VPN, no direct DB access

**Decision:** IEP2 (Jetson) sends tracking batches to EEP via HTTPS POST (`/internal/stores/{store_id}/tracking-batch`). EEP writes to the database and signals IEP3. Jetsons never hold database credentials.

**Why:** The alternative (direct Postgres write + direct Redis publish from Jetson) breaks at multiple stores:
1. Each Jetson would need the database password — a compromised device exposes all stores' data.
2. VPN (WireGuard) requires manual key exchange per device, scales to ~20 stores before becoming unmanageable.
3. RDS in a private VPC subnet is unreachable from the public internet by design.

HTTP to EEP solves all three: one per-store API key, no VPN, EEP is the only public surface. Adding a new store means generating a new API key, not reconfiguring network topology.

**Auth:** `X-Internal-Token` header shared between IEP2 and EEP, rotated per store.

---

## ADR-003 — Local Kafka (Redpanda) on Jetson, no cloud Kafka

**Decision:** Redpanda runs as a k3s pod on the Jetson. It carries only IEP1 → IEP2 frame-reference events. No cloud Kafka exists.

**Why:** Kafka's value is decoupling services across machines. IEP1 and IEP2 both run on the same Jetson — a local bus costs nothing and adds no network latency. Cloud Kafka (MSK) for this workload costs ~$95/month and exposes Kafka on the internet (a security anti-pattern).

IEP3 is triggered via Redis streams published by EEP after it writes each tracking batch — no cloud Kafka needed.

---

## ADR-004 — Per-store IEP3 pod, shared EEP

**Decision:** One IEP3 Deployment per store (namespace: `retail-edge`, label: `store={store_id}`). EEP scales horizontally and serves all stores.

**Why:** IEP3 maintains per-store state — the batch coordinator tracks which cameras have reported for each batch window. Sharing one IEP3 across stores requires store_id routing inside a single process, which couples stores together (one store's slow batch delays another's reconciliation). One pod per store is isolated and cheap (~256MB RAM each).

EEP is stateless — it reads from DB per request. Any replica serves any store. Horizontal Pod Autoscaler (HPA) on CPU scales EEP as the number of stores grows.

**Onboarding a new store:** `cp -r infra/cloud/stores/template infra/cloud/stores/{store_id}` → replace `STORE_ID` → `kubectl apply -k infra/cloud/stores/{store_id}/`.

---

## ADR-005 — k3s on EC2 instead of Fargate or EKS

**Decision:** k3s runs on two EC2 instances (t3.medium master + t3.small worker). No EKS, no Fargate.

**Why Kubernetes at all:** IEP3 is one-pod-per-store — Kubernetes namespace isolation, rolling deploys, and health restarts are exactly right for this pattern. EEP benefits from HPA scaling as store count grows.

**Why not Fargate:** Fargate charges per-second for always-on tasks. EEP + IEP3 run continuously. At current scale (1–20 stores) Fargate costs $44–$260/month for compute alone. k3s on EC2 costs $34–$50/month for the same compute regardless of store count.

**Why not EKS:** EKS charges $73/month for the control plane before any workloads. k3s runs the control plane on the master EC2 at no additional cost. Switch to EKS when store count exceeds ~50 or when the team needs managed upgrades.

**Why not a single EC2 with Docker Compose:** No rolling updates, no per-store pod isolation, manual health management. Kubernetes primitives (readiness probes, rolling deploys, resource limits) are worth the setup cost at this scale.

---

## ADR-006 — Redis Streams for IEP2 → IEP3 signaling

**Decision:** EEP publishes to `stream:store:{store_id}:batch_complete` after writing each tracking batch. IEP3 uses `XREADGROUP` with consumer groups.

**Why Streams over pub/sub:** Redis pub/sub drops messages if IEP3 is down. Streams persist the message until IEP3 acknowledges it. When IEP3 restarts after a crash, it reads from its last-acknowledged position — no batches are lost or double-processed.

**Why per-store streams:** One shared stream with all stores' events forces IEP3 to filter by store_id. With one stream per store, each IEP3 pod only sees its own events. Simpler, no cross-contamination.

---

## ADR-007 — Shared RDS, partitioned by store_id

**Decision:** One RDS PostgreSQL instance for all stores. All tables include `store_id` as a partition key. Row-level security enforced at the application layer by EEP.

**Why:** At 1–20 stores, separate RDS instances would cost $13–$260/month in DB fees alone. A single t3.small handles 20 stores comfortably. When query latency degrades (typically >30 stores), add a read replica or move to partitioned tables.

**Rejected alternative:** One RDS per store. Clean isolation but uneconomical. Revisit if per-store compliance requirements demand full data segregation.

---

## ADR-008 — Local filesystem for frames, not S3 round-trip

**Decision:** `IEP1_FRAME_STORAGE=filesystem`. IEP1 writes frames to a shared PVC. IEP2 reads them via `file://` URI. S3 is not used for frame transport.

**Why:** IEP1 and IEP2 share the same Jetson. Uploading a frame to S3 in Bahrain (100ms) and downloading it back (100ms) for immediate processing is 200ms of wasted latency per frame. At 2fps/4 cameras, that's 1.6MB/s of unnecessary bandwidth. The shared PVC delivers frames in 1ms.

S3 is still provisioned and available for explicit archival if needed, with a 2-hour lifecycle rule on the `vision-frames/` prefix to prevent accumulation.

---

## Cost summary (me-south-1, single store)

| Component | $/month |
|-----------|---------|
| EC2 t3.medium (k3s master: EEP, Redis, Nginx) | ~$34 |
| EC2 t3.small (k3s worker: IEP3 pods) | ~$16 |
| RDS t3.micro (shared, all stores) | ~$13 |
| CloudFront + S3 frontend | ~$5 |
| S3 frames (2hr lifecycle) | ~$1 |
| **Total (1 store)** | **~$69/month** |
| **Per 5 additional stores** | **+$16 (new worker node)** |
| **20 stores** | **~$133/month** |
