# RetailVision — Error Backlog

Structured log of every identified issue, root cause, and final fix.
Each entry follows the format:

```
### BUG-NNN — <short title>
**Status:** Open | Fixed | Won't Fix
**Service(s):** <affected services>
**Severity:** Critical | High | Medium | Low
**Symptom:** What the user/system observed
**Root Cause:** Specific file:line and explanation
**Fix:** Minimal correct change applied
**Verification:** How the fix was confirmed
**Notes:** Systemic or architectural implications
```

---

## Open Issues

*(none)*

---

## Fixed Issues

### BUG-001 — PgBouncer image not found on Docker Hub
**Status:** Fixed  
**Service(s):** `docker-compose.yml` → `pgbouncer` service  
**Severity:** Critical (blocks entire stack from starting)  
**Symptom:** `docker compose up` fails with `failed to resolve reference "docker.io/pgbouncer/pgbouncer:1.22.1": not found`  
**Root Cause:** Two compounding issues: (1) `pgbouncer/pgbouncer` is an abandoned image (last tag `1.15.0`, 2020) — wrong namespace entirely. (2) The correct image is `edoburu/pgbouncer`, but its tag format includes a patch suffix (`1.22.1-p0`), not a bare version string (`1.22.1`).  
**Fix:** Changed `docker-compose.yml` line 65: `pgbouncer/pgbouncer:1.22.1` → `edoburu/pgbouncer:1.22.1-p0`. The `edoburu/pgbouncer` image uses identical config paths (`/etc/pgbouncer/pgbouncer.ini`, `/etc/pgbouncer/userlist.txt`) and ships `psql` for the healthcheck. No changes to config files or healthcheck required.  
**Verification:** Re-run `docker compose up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge`; pgbouncer should reach healthy status.  
**Notes:** No systemic implications — isolated to wrong image reference in compose.

---

### BUG-002 — YOLO and OSNet services not runnable on x86 / Intel (no Jetson/CUDA)
**Status:** Fixed  
**Service(s):** `yolo-service`, `osnet-service`, `docker-compose.dev.yml`  
**Severity:** Critical (blocks dev stack on any non-Jetson machine)  
**Symptom:** `docker compose build` fails because `nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3` is an ARM64/Jetson-only base image; TRT/pycuda deps are unavailable on x86.  
**Root Cause:** Both inference service Dockerfiles are pinned to the Jetson JetPack base image and require TensorRT + pycuda, which are NVIDIA-GPU/ARM64-only. No CPU fallback existed.  
**Fix:** Created CPU dev variants without changing any production files:
- `services/yolo_service/Dockerfile.dev` — `python:3.11-slim` base, CPU torch, ultralytics `.pt` model
- `services/yolo_service/service_dev.py` — identical ZMQ wire protocol, loads `yolov8n.pt` on CPU
- `services/yolo_service/requirements.dev.txt`
- `services/osnet_service/Dockerfile.dev` — `python:3.11-slim` base, CPU torch+torchvision, ResNet-18 (512-dim avgpool, same L2-norm wire format)
- `services/osnet_service/service_dev.py` — identical ZMQ wire protocol, no TRT/pycuda
- `services/osnet_service/requirements.dev.txt`
- Updated `docker-compose.dev.yml` to override builds for both services + set `ML_SERVICES_TIMEOUT_S=300`  
**Verification:** Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml build yolo-service osnet-service`; both should build successfully on x86.  
**Notes:** ResNet-18 produces valid 512-dim L2-normalised embeddings — full pipeline works end-to-end. ReID matching quality is lower than OSNet but sufficient for dev testing. IEP2, IEP1, EEP, IEP3 are unchanged.

---

## Won't Fix / By Design

*(none recorded yet)*
