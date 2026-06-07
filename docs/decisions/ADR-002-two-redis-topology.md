# ADR-002: Two-Redis topology (edge-local + cloud)

**Status:** Accepted
**Date:** TODO
**Deciders:** TODO (team members)

## Context

The system has two distinct environments: the edge device (physically in the store) and the cloud (Kubernetes cluster). Both need Redis for stream-based messaging, but their requirements differ fundamentally.

## Decision

Run two separate Redis instances:
1. **Edge-local Redis** — runs on the edge device, loopback-only, ephemeral
2. **Server Redis** — runs in the cloud Kubernetes cluster, persistent, accessible by IEP3 and Live Bridge

## Rationale

| Concern | Edge-local Redis | Server Redis |
|---|---|---|
| Network exposure | Loopback-only — never exposed to internet | Internal k8s service — not public |
| Data lifetime | Ephemeral — streams cleared after IEP2 publishes batch_complete | Persistent — IEP3 reads from here |
| Latency | Sub-millisecond (loopback) | LAN latency within k8s cluster |
| Privacy | Raw frame metadata never crosses the network | Only compact batch_complete events arrive here |

## Alternatives considered

**Single cloud Redis:** Would require streaming all IEP1/IEP2 intermediate data (frame paths, per-frame embeddings) to the cloud — high bandwidth, high latency for edge-side consumers.

**Single edge Redis:** IEP3 would need to be on the edge device — eliminates cloud scaling, increases edge hardware requirements.

## Consequences

- IEP2 must write to edge-local Redis AND signal IEP3 via the cloud Redis stream:iep2:batch_complete
- The batch_complete event is the only data that crosses the edge→cloud boundary (compact: just IDs and counts)
