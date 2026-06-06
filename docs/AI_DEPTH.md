<!--
  Rubric: T1 — AI depth and non-triviality (5%)
  This document proves the system is non-trivial AI, not a wrapper.
-->

# AI pipeline depth — RetailVision

## 1. Why this problem requires ML
<!-- TODO: Explain why rule-based systems cannot solve cross-camera re-identification -->

## 2. The full inference chain
<!-- TODO: IEP1 → IEP2 → IEP3, each stage with inputs, outputs, and the AI decision being made -->

## 3. IEP2: per-camera vision pipeline

### 3.1 Person detection (YOLO)
<!-- TODO: Model variant chosen, input resolution, confidence threshold, why this model -->

### 3.2 In-frame tracking (ByteTrack)
<!-- TODO: How local track IDs are maintained across frames, what ByteTrack does differently -->

### 3.3 Appearance embedding (OSNet ReID)
<!-- TODO: Embedding dimensionality, what the vector encodes, why appearance over position -->

## 4. IEP3: cross-camera reconciliation

### 4.1 Cosine similarity matching
<!-- TODO: The math, the threshold value chosen, why cosine over Euclidean distance -->

### 4.2 Global identity state machine
<!-- TODO: ACTIVE → LOST → EXITED transitions, conditions for each -->

### 4.3 Windowed batch alignment
<!-- TODO: Why 60 s window, how all cameras are synchronized, what happens if one camera is late -->

## 5. Model selection rationale
<!-- TODO: YOLO variant benchmark (from docs/docs_models/detection/), OSNet variant benchmark (from docs/docs_models/reid/) -->

## 6. Why this pipeline is non-trivial
<!-- TODO: What simpler approaches fail at, what measurably improves with this full chain -->
