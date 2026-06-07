# ADR-003: Fixed 60-second windowed batch processing

**Status:** Accepted
**Date:** TODO
**Deciders:** TODO

## Context

IEP3 must correlate detections from multiple cameras to resolve cross-camera identities. This requires that all cameras' outputs are aligned in time — otherwise IEP3 cannot know which camera-A detections correspond to which camera-B detections.

## Decision

Process in fixed 60-second windows. All IEP2 instances (one per camera) emit `batch_complete` at the end of each window. IEP3 waits for all cameras in a store to report for window N before running reconciliation.

## Rationale

A fixed window creates a natural synchronization barrier. All cameras share the same window boundaries (defined by wall clock, aligned to the minute), so IEP3 simply waits for all N cameras to signal `batch_complete` for window W.

**Why 60 seconds:** Retail analytics does not require sub-minute granularity. Dwell time, occupancy, and flow metrics are meaningful at 1-minute resolution. Shorter windows increase IEP3 invocation frequency without improving analytical value.

## Alternatives considered

**Continuous streaming join:** Real-time stateful stream joining across N camera streams (e.g., Flink-style windowed joins). Rejected: requires complex distributed state management, ordering guarantees, and watermarking — disproportionate complexity for the retail analytics use case.

**Per-frame reconciliation:** Run IEP3 after every frame. Rejected: O(frames × cameras) reconciliation invocations, high PostgreSQL write amplification.

## Consequences

- Maximum analytics latency: ~60 seconds (acceptable for retail use case)
- IEP3 must handle the case where one camera is slow or offline (timeout logic needed)
- All IEP2 instances must use identical window boundaries — governed by wall clock, not relative timers
