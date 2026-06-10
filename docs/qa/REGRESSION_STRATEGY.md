<!--
  Rubric: Q2 — Regression / validation strategy (2.5%)
-->

# Regression and validation strategy — RetailVision

## 1. Golden dataset test for IEP3

**Purpose:** Verify that IEP3's cross-camera matching produces deterministic, correct results on a fixed input.

**Dataset location:** `testing-data/golden/`

**Test scenario:**
- 3 simulated cameras
- 2 persons walking through overlapping camera zones
- Pre-computed resnet50_msmt17 embeddings (fixed, no randomness)
- Expected output: person A → global_id X, person B → global_id Y (no false merges)

**How to run:**
```bash
pytest tests/unit/iep3/test_golden_dataset.py -v
```

**Tolerance:** Global ID assignment must be 100% correct (no false merges, no missed links) for this fixed scenario.

## 2. Model version regression tests

When a new detection or ReID model is considered for promotion:
1. Run it against the golden dataset
2. Check that IEP3 still produces correct global_id assignments
3. Verify latency benchmarks (see MLOPS_PIPELINE.md §3 for thresholds)
4. Only promote if all thresholds pass

## 3. Data validation checks

| Check | What it validates | Where implemented |
|---|---|---|
| tracking_history schema | All required columns present, types correct | TODO |
| ReID embedding dimensions | 2048-dim float32 vector (resnet50_msmt17) | TODO |
| Homography matrix validity | 3×3 matrix, determinant ≠ 0 | TODO |
| Window alignment | All cameras in a batch share the same window_id | IEP3 pre-condition check |

## 4. Non-determinism handling

IEP3 is deterministic for fixed inputs (cosine similarity on fixed embeddings has no randomness).
If non-determinism is introduced (e.g., future LLM analytics component), the following approach applies:
<!-- TODO: How would you test a non-deterministic component? -->
