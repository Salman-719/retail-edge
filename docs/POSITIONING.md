<!--
  Rubric: P1 (problem clarity), P2 (baseline rigor), P3 (AI justification), P4 (value/publishability)
-->

# Problem statement and AI justification — RetailVision

## 1. The business problem
<!-- TODO: Retailers have cameras everywhere but cannot track customer journeys across camera boundaries.
     A customer seen by 5 cameras generates 5 disconnected fragments, not one journey.
     Fill in with specifics: what decisions this blocks, what data is currently unusable. -->

## 2. Who would deploy this
<!-- TODO: Large grocery chains, malls, retail analytics vendors.
     Decision maker: store operations or loss prevention teams.
     Who pays, and what budget category this falls under. -->

## 3. Non-AI baseline

### Baseline A: single-camera tracking only
<!-- TODO: What it can and cannot do. Quantify the gap: N cameras → N×M disconnected tracks/hour. -->

### Baseline B: zone-entry IR / pressure sensors
<!-- TODO: What it can and cannot do. No trajectory, no dwell time, no cross-zone path. -->

### Baseline C: manual counting / time-lapse review
<!-- TODO: Labor cost, sampling rate, accuracy -->

**Quantitative gap vs. RetailVision:**
<!-- TODO: Measurement or estimate of how much better RetailVision is on a specific metric -->

## 4. Why AI is necessary
<!-- TODO:
     - Rule-based cross-camera matching fails because pixel position is invalid across non-overlapping cameras
     - Time alone is ambiguous (many people move between cameras simultaneously)
     - Appearance-based ReID is the only generalizable signal
     - Back this up with a number: ReID achieves X% match accuracy vs Y% for time-only heuristic -->

## 5. Real-world value
<!-- TODO:
     - Dwell time optimization: zones with >90 s avg dwell convert at 2× rate (cite or estimate)
     - Occupancy compliance: real-time alert when zone exceeds fire-code limit
     - Path analysis: identify bottlenecks between entrance and checkout -->

## 6. Novelty claim
<!-- TODO: What makes RetailVision different from existing retail analytics products.
     Cross-camera ReID + homography floor projection + production multi-tenant deployment
     is not a research notebook — argue why this is deployable and novel in the cohort. -->
