# Retail Edge k3s Deployment

This directory is the first production-shaped k3s target for IAIP1 + IAIP2.

## What It Runs

- EEP and frontend.
- IAIP1 ingestion API and stream publisher.
- IAIP2 detector/local ReID workers consuming `vision.frame_ref.v1`.
- IEP3 reconciliation, which owns global cross-camera ReID from IAIP2 batch-complete events.
- Redpanda, Postgres, Redis, and MinIO for local k3s development.
- KEDA `ScaledObject` definitions for detector queue lag scaling.

## Local k3s Notes

Build/push or import these images into k3s before applying:

- `retail-edge/eep:latest`
- `retail-edge/frontend:latest`
- `retail-edge/iep1-ingestion:latest`
- `retail-edge/iep2-vision:latest`
- `retail-edge/iep3-reconciliation:latest`

Then apply:

```bash
kubectl apply -k infra/k8s
```

`secrets.example.yaml` is wired as a dev secret so the stack can render and run
locally. Replace it with real sealed/external secrets before any shared
environment.

The local default uses a shared frame-cache PVC between IAIP1 and detector
workers. For production, set `IEP1_FRAME_STORAGE=s3` and use MinIO/S3 frame
references instead of the filesystem cache.
