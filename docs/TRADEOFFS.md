<!--
  Rubric: T5 — Tradeoff evidence (5%)
  Required: ≥3 tradeoffs, each with: what was chosen, what was rejected, and evidence.
-->

# Engineering tradeoffs — RetailVision

> For each tradeoff: state what was chosen, what was rejected, why, and provide evidence (benchmark, measurement, or experiment).

## Tradeoff 1: Edge vs. cloud processing

**Decision:** Heavy vision (YOLO, ByteTrack, OSNet) runs on edge; identity reconciliation runs in cloud.

**Alternative considered:** Stream all raw video frames to cloud for centralized processing.

**Why rejected:**
<!-- TODO: Bandwidth cost (MB/s per camera at target_fps), privacy risk, latency -->

**Evidence:**
<!-- TODO: Measured bandwidth at target_fps, cost calculation -->

---

## Tradeoff 2: XACK-before-processing vs. at-least-once delivery

**Decision:** IEP3 acknowledges Redis messages before processing (see ADR-001).

**Alternative considered:** Acknowledge after processing (at-least-once guarantee).

**Why rejected:**
<!-- TODO: Duplicate batch processing would corrupt global_id state — explain why -->

**Evidence:**
<!-- TODO: Crash simulation result, or reasoning about state corruption -->

---

## Tradeoff 3: Fixed 60 s window vs. continuous streaming reconciliation

**Decision:** Fixed windowed batches align all cameras before IEP3 runs.

**Alternative considered:** Real-time stateful stream joining across N camera streams.

**Why rejected:**
<!-- TODO: Complexity of stateful stream joins, ordering guarantees needed -->

**Evidence:**
<!-- TODO: Latency is acceptable for retail analytics at 60 s granularity — justify -->

---

## Tradeoff 4: Cosine similarity threshold tuning

**Decision:** Threshold = TODO (fill in value).

**Alternatives tested:** 0.40, 0.50, 0.60, 0.70

**Evidence:**
<!-- TODO: MLflow run IDs, precision/recall table per threshold -->

| Threshold | Precision | Recall | False merge rate |
|---|---|---|---|
| 0.40 | TODO | TODO | TODO |
| 0.50 | TODO | TODO | TODO |
| 0.60 | TODO | TODO | TODO |
| 0.70 | TODO | TODO | TODO |

**Decision rationale:**
<!-- TODO: Why the chosen threshold balances precision vs recall for retail use case -->

---

## Tradeoff 5: YOLO variant selection

**Decision:** TODO (e.g., YOLOv8-m on Jetson with TensorRT).

**Alternatives tested:** TODO (e.g., YOLOv8-nano, RT-DETR)

**Evidence:**
<!-- TODO: Latency and mAP benchmark table from docs/docs_models/detection/ -->

| Model | Latency (ms/frame) | mAP@0.5 | Fits Jetson? |
|---|---|---|---|
| TODO | TODO | TODO | TODO |
