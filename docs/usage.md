# Usage Guide — Operating RetailVision

How to use the platform day to day once it's deployed. For standing the system
up, see [deploy-cloud.md](deploy-cloud.md) (cloud) and [deploy-edge.md](deploy-edge.md) (Jetson).

The web GUI is served at the cluster's ingress: **`http://<MASTER_IP>/`**.

---

## Quick start — first run in the GUI

Do this once after the cloud is deployed (the edge can come later):

1. **Open** `http://<MASTER_IP>/`
   *(get the IP on the Mac: `aws cloudformation describe-stacks --region eu-west-1 --stack-name RetailEdgeCluster --query "Stacks[0].Outputs[?OutputKey=='MasterPublicIp'].OutputValue" --output text`)*
2. **Register** the owner account → lands on the Owner Dashboard.
3. **Create a store.** Use the **same store UUID** you onboarded in the cloud
   (cloud deploy Step 9). The per-store IEP3 pod is keyed to that ID.
4. **Open the store** (`/store/<slug>/`) → **Store Config**, then in order:
   **Cameras** → **Zones** (assign roles) → **Calibration** (homography per camera).
5. **Verify the pipeline** once a Jetson is streaming:
   - **Live Monitoring** → "Edge Online" badge + green camera dots
   - **Live View** → annotated video with bounding boxes + IDs
   - **Analytics** → occupancy, dwell time, heatmaps

Without a streaming edge you can still register, create the store, and configure
cameras/zones — the live/analytics views populate once tracking data flows in.

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

## 3a. Confirm the edge is connected (no config needed)

You don't need cameras, zones, or calibration to verify the Jetson is reaching
the cloud. IEP1 sends a **store-level heartbeat** every ~15s as soon as it starts
(it only needs `IEP1_AUTO_START_STORE_ID`).

- **In the GUI:** Live Monitoring shows a green **"Edge connected (hostname)"**
  banner when the Jetson is reachable, and an amber "Edge not connected" banner
  otherwise. Flips to disconnected ~60s after the Jetson stops.
- **From the CLI:**
  ```bash
  curl -s "http://<MASTER_IP>/api/store/<slug>/vision/edge-status"
  # {"connected": true, "last_seen": "...", "hostname": "saljetson-desktop"}
  ```

This is the quickest end-to-end check while building: deploy the Jetson → see
"Edge connected" — before configuring anything else.

---

## 4. Viewing results

| Page | Path | What it shows | Data source |
|------|------|---------------|-------------|
| **Live Monitoring** | `/store/<slug>/live` | Camera/edge status + occupancy KPIs and active alerts | **mixed** — see below |
| **Live View** | `/store/<slug>/live-view` | Annotated camera video with bounding boxes + global/local IDs | live (edge stream) |
| **Analytics** | `/store/<slug>/analytics` | Zone occupancy, dwell time, traffic trends, heatmaps | live (DB) |
| **AI Assistant** | `/store/<slug>/agent` | Natural-language questions over the store's analytics | live (DB) |

> **Live Monitoring — what's wired vs. demo.** These are **real**: the
> **Edge connected** banner (store-level heartbeat, `…/vision/edge-status`) and
> the **Camera Status** strip (`…/vision/camera-health`, polled every 10s). These
> are still **demo placeholders**: **Total People / Customers / Staff / Active
> Alerts** tiles and the floor-plan dots — they aren't wired to live endpoints
> yet, so don't read those numbers as real. The amber demo banner only shows
> while the edge is disconnected.

Cross-camera identities (the same person seen on camera A then B getting one
`global_id`) appear once IEP3 has reconciled a batch — within a few seconds of
the batch window closing.

> If a freshly deployed frontend still shows old camera names (CAM-01…04) or no
> "Edge Online" badge, your browser cached the old bundle — hard-refresh
> (Cmd/Ctrl+Shift+R) after `kubectl rollout restart deployment/frontend`.

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
