# ADR-004: Edge vs. cloud processing split

**Status:** Accepted
**Date:** TODO
**Deciders:** TODO

## Context

The system must process video from N cameras per store. Video is bandwidth-heavy and privacy-sensitive. Two extreme architectures are possible: process everything on the edge, or process everything in the cloud.

## Decision

Split processing at the semantic boundary:
- **Edge:** pixel-level work (RT-DETR-x detection, BoTSORT tracking, resnet50_msmt17 ReID embedding extraction, homography projection)
- **Cloud:** cross-camera reasoning (IEP3 identity reconciliation), management plane (EEP), analytics, UI

## Rationale

**Why heavy vision on edge:**
- Raw video bandwidth: TODO MB/s per camera at target_fps — streaming N cameras to cloud is prohibitive
- Privacy: raw frames never leave the store as a continuous stream
- Latency: GPU inference on Jetson is faster than round-trip to cloud GPU

**Why reconciliation in cloud:**
- IEP3 needs embeddings from ALL cameras simultaneously — gathering these in the cloud is cleaner than on-device
- Cloud resources are elastic — IEP3 can scale if store camera count grows
- Management plane (EEP) naturally belongs in the cloud (multi-tenant, always-on)

## Data that crosses the boundary

Only compact metadata crosses the gRPC link:
- `StartCamera` / `StopCamera` commands (EEP → Edge)
- `batch_complete` events (Edge → IEP3 via cloud Redis): just IDs and counts
- Presigned thumbnail URLs (Edge MinIO → browser): small JPEGs, on-demand only

## Alternatives considered

**All-cloud:** Stream all raw video to cloud. Rejected: bandwidth cost, privacy risk, latency.
**All-edge:** Run IEP3 on edge device. Rejected: requires high-memory edge hardware, prevents multi-store management, limits analytics scalability.

## Consequences

- Edge device must have GPU (Jetson) for RT-DETR-x detection + resnet50_msmt17 ReID
- gRPC link must be reliable — Edge Agent implements reconnect logic
- Edge device must handle cloud connectivity loss gracefully (IEP1/IEP2 continue buffering locally)
