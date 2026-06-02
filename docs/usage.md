# Usage Guide — Operating RetailVision

How to use the platform day to day once it's deployed. For standing the system
up, see [deploy-cloud.md](deploy-cloud.md) (cloud) and [deploy-edge.md](deploy-edge.md) (Jetson).

The web GUI is served at the cluster's ingress: **`http://<MASTER_IP>/`**.

---

## 1. Accounts and stores

The platform is multi-tenant: an **owner** account manages one or more **stores**,
and can invite **members** with scoped roles.

1. **Register** — `/register`, create the owner account.
2. **Owner dashboard** — `/dashboard`, lists your stores. Create a store here.
3. **Open a store** — routes are store-scoped under `/store/<slug>/...`.

> The store you create in the GUI must correspond to the `STORE_ID` you onboarded
> in cloud deploy Step 9 (the IEP3 pod is per-store). Keep the two in sync.

---

## 2. Store configuration

**Store Config** (`/store/<slug>/config`) is where you define what the vision
pipeline needs. Do this before expecting any tracking data.

1. **Cameras** — add each physical camera. Each gets a UUID; this is the
   `camera_id` that flows through IEP1 → IEP2 → reconciliation.
2. **Zones** — draw polygon zones on the floor plan and assign a **role**
   (entrance, exit, checkout, shopping, staff_only, general). Roles drive
   entrance/exit counting and alert rules.
3. **Calibration** — set each camera's homography (image → floor-plan mapping)
   so detections project onto real floor coordinates.

Changes here are read automatically by the backend:
- IEP3 re-reads the store's camera list every 30s (no restart needed).
- Edge IEP1 fetches the camera topology from EEP on startup (or restart the
  edge ingestion pod to pick up new cameras immediately).

---

## 3. Running the pipeline

Tracking data originates on the **edge** (Jetson), not in the GUI:

```
Cameras → IEP1 (sample frames) → IEP2 (detect/track/ReID, GPU)
        → POST tracking batch → EEP → DB + Redis stream
        → IEP3 (cross-camera reconciliation) → global identities → DB
        → GUI reads results
```

**Two ways to feed it:**

- **Live** — point IEP1 at RTSP camera URLs (configured per camera). The edge
  auto-starts ingestion when `IEP1_AUTO_START_STORE_ID` is set on the Jetson.
- **Test1 simulator** — replay sample videos through the same pipeline:
  ```bash
  kubectl -n retail-edge exec deploy/iaip1-ingestion -- \
    curl -s -X POST localhost:8001/simulators/test1/runs \
    -H "Content-Type: application/json" -d '{"sample_rate_fps": 2.0}'
  ```

---

## 4. Viewing results

| Page | Path | What it shows |
|------|------|---------------|
| **Live Monitoring** | `/store/<slug>/live` | Real-time per-camera status and current occupancy |
| **Live View** | `/store/<slug>/live-view` | Annotated camera video with bounding boxes + global/local IDs |
| **Analytics** | `/store/<slug>/analytics` | Zone occupancy, dwell time, traffic trends, heatmaps |
| **AI Assistant** | `/store/<slug>/agent` | Natural-language questions over the store's analytics |

Cross-camera identities (the same person seen on camera A then B getting one
`global_id`) appear once IEP3 has reconciled a batch — within a few seconds of
the batch window closing.

---

## 5. Management

| Page | Path | Purpose |
|------|------|---------|
| **Employees** | `/employees` | Enroll staff (ReID gallery) so they're distinguished from customers |
| **Shifts** | `/shifts` | Staff schedules; feeds the "no staff present" alert rule |
| **Members** | `/members` | Invite users to this store with roles; manage access |
| **Audit Log** | `/audit` | Record of configuration and access changes |
| **Settings** | `/settings` | Store-level preferences |

---

## 6. Operating the backend

Common operational tasks (full reference in [deploy-cloud.md](deploy-cloud.md)):

```bash
# Pod health
kubectl -n retail-edge get pods

# EEP autoscaling status (2→6 on CPU/mem)
kubectl -n retail-edge get hpa

# IEP3 logs for a store (reconciliation activity)
kubectl -n retail-edge logs -f deployment/iep3-<STORE_ID>

# Edge ingestion / vision logs (on the Jetson)
kubectl -n retail-edge logs -f deploy/iaip1-ingestion
kubectl -n retail-edge logs -f deploy/iaip2-detector-workers
```

**When you change something:**
- GUI data (cameras, zones) → picked up automatically (≤30s for IEP3).
- A service's code → rebuild its image, then `kubectl rollout restart deployment/<name>`.
- A manifest in `infra/cloud/` → `kubectl apply -k infra/cloud/`.

---

## 7. Onboarding additional stores

1. Cloud deploy [Step 9](deploy-cloud.md) — create the per-store IEP3 pod.
2. Create the matching store in the GUI (Section 1) and configure it (Section 2).
3. Deploy a Jetson for that store ([deploy-edge.md](deploy-edge.md)) pointed at
   the same `STORE_ID` and the shared `VISION_INTERNAL_TOKEN`.
