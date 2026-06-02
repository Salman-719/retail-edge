# RetailVision Documentation

Documentation is split by purpose. Start with the one that matches what you need.

| Doc | For | Read when |
|-----|-----|-----------|
| [architecture-decisions.md](architecture-decisions.md) | Engineers, reviewers | Understanding *why* the system is built this way (edge/cloud split, k3s, per-store IEP3, Redis streams, ADRs) |
| [deploy-cloud.md](deploy-cloud.md) | Whoever stands up AWS | Deploying the cloud side (CDK → k3s on EC2 → EEP, IEP3, Redis, frontend, ingress, autoscaling) |
| [deploy-edge.md](deploy-edge.md) | Whoever sets up a store | Deploying a Jetson at a store (k3s, GPU, IEP1 + IEP2, Redpanda) |
| [usage.md](usage.md) | Store operators, owners | Operating the platform via the GUI (onboard store, configure cameras/zones, view analytics, manage staff) |

---

## Typical order for a fresh deployment

1. **Read** [architecture-decisions.md](architecture-decisions.md) to understand the moving parts.
2. **Deploy cloud** — [deploy-cloud.md](deploy-cloud.md) (one-time per environment).
3. **Deploy edge** — [deploy-edge.md](deploy-edge.md) (once per store / Jetson).
4. **Operate** — [usage.md](usage.md) (ongoing).

## System at a glance

```
EDGE (Jetson, per store)            CLOUD (AWS eu-west-1, k3s on EC2)
────────────────────────            ─────────────────────────────────────────
Cameras → IEP1 (ingest)             EEP (API + ingress)  ⇄  RDS PostgreSQL
        → IEP2 (detect/track/ReID)  IEP3 (reconcile, per store)
        → HTTPS POST tracking ────► Redis (batch_complete streams)
                                    Frontend (GUI)
```

- **Edge** runs GPU detection/tracking and posts results to the cloud over HTTPS.
- **Cloud** persists data, reconciles cross-camera identities, and serves the GUI.
- No database credentials or VPN on the edge — only an `EEP_BASE_URL` + shared token.
