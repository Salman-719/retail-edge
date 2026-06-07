# Deploy — Edge Device  (moved)

> **This document has moved.** The authoritative edge procedure now lives in
> **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — Part C**:
>
> - C0 prerequisites · C1 inputs (agent secret + CA) · C2 bootstrap ·
>   C3 verify · **C4 build the GPU images on the Jetson** · **C5 expose the GPU to k3s**
>
> This older doc predated the edge fixes (keep flannel CNI, GHCR owner in the
> kustomization, non-fatal rollout waits, Jetson-built `yolo`/`osnet` images,
> GPU runtime config) and would reproduce solved issues. Use DEPLOYMENT_GUIDE.md.
