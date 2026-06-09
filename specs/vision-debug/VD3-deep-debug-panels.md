# VD3 — Deep-Debug Panels

_Now show the reasoning. Four panels turn the reconciliation trace (VD1) plus the existing mapping
into answers: who became whom, why these two tracks merged (or didn't), how similar they looked, and
why a given floor position was chosen as canonical._

## Non-obvious tooling / facts

- VD1 exposes `GET /api/debug/dev/iep3/trace?store_id&batch_number` with `event_type` ∈
  `graph | spatial_vote | reid_fallback | selection` and a typed `detail` JSONB.
- `global_local_mapping` (local↔global↔camera) is already persisted — the local→global panel reads it
  directly (add a tiny dev read if `getDevIep3` doesn't already include it).
- Within-camera `reid_sim`/`reid_matched` already arrive on the live-bridge detections; cross-camera
  cosine comes from the trace's `reid_fallback` events.
- Panels are **trace-dependent**: when the trace flag was off, degrade gracefully (show "enable trace
  to see merge decisions") rather than erroring.

## Architectural map

```
components/devE2E/recon/
  LocalGlobalPanel.jsx     table: (camera, local#) → global#  [+ which batch linked them]
  MergeDecisionPanel.jsx   per camera-pair: confirmed/ambiguous + vote_rate, votes, co_visible
  ReidSimilarityPanel.jsx  within-camera reid_sim (live) + cross-camera cosine vs threshold (trace)
  SelectionScorePanel.jsx  per IEP3 global position: chosen source camera + score components
api.js                     + getDevReconTrace(store_id, batch?) ; getDevLocalGlobal(store_id) if needed
```

## Read before implementing

- [VD1-iep3-recon-trace.md](VD1-iep3-recon-trace.md) (the trace endpoint + detail shapes)
- [dev_pipeline.py get_iep3](../../services/eep/app/api/routers/dev_pipeline.py#L403) (does it already join `global_local_mapping`?)
- [VD2-frontend-redesign.md](VD2-frontend-redesign.md) (shared identity colors/numbers to reuse here)

## Rules (verifiable)

1. **Local→Global panel**: from `global_local_mapping`, list each `(camera, local#) → global#` using
   the **shared identity color/number** (VD2). This is the through-line; it needs no trace. If
   `getDevIep3` doesn't already return the mapping, add a dev read.
2. **Merge-decision panel**: from trace `spatial_vote` events, group by camera pair; show each
   candidate `(local_a ↔ local_b)` with `vote_rate`, `votes`, `co_visible`, and class
   (confirmed/ambiguous), colored by outcome. This is the literal "why these merged / why ambiguous."
3. **ReID similarity panel**: show within-camera `reid_sim` (from live detections, matched✓/✗) and,
   from trace `reid_fallback`, the cross-camera `cosine` vs `threshold` and `matched`. A compact
   per-pair list or small matrix — make the threshold and pass/fail explicit.
4. **Selection-score panel**: from trace `selection` events, per IEP3 global position show the chosen
   `source_camera`, the final `score`, and its `components`, so "why this camera's position won" is
   legible.
5. **Batch scoping**: all panels respect a selected batch (or "latest") so the user can step through
   reconciliation batch by batch (pairs with the replay ethos).
6. **Graceful degradation**: trace off / no rows → an explicit "enable trace (dev start) to see merge
   reasoning" state, never an error; the Local→Global panel still works (no trace needed).
7. **Live + replay**: panels poll while running and remain readable after Stop (the trace table
   survives — VD1), matching the camera replay.

## Acceptance

- Local→Global panel shows the same numbers/colors as the feeds and map (VD2) for the same people.
- For two overlapping cameras seeing one person, the merge-decision panel shows a `confirmed` pair
  with a real `vote_rate`/`votes`/`co_visible`; an ambiguous case shows as ambiguous.
- The ReID panel shows within-camera sims and, on a fallback, the cross-camera cosine vs threshold and
  the pass/fail.
- The selection panel shows, for a global position, which camera was chosen and the score components.
- With the trace flag off, the merge/ReID/selection panels show the "enable trace" state while
  Local→Global still renders.
- Stepping batch-by-batch updates all panels consistently.

## Hard constraints & anti-patterns

- **Do NOT** require the trace for the Local→Global panel — it reads persisted mapping.
- **Do NOT** error when the trace is absent — degrade with a clear prompt.
- **Do NOT** invent similarity/score numbers client-side — render exactly what the trace recorded.
- **Do NOT** diverge identity colors/numbers from VD2 — one identity map across the whole screen.

## Pinned versions

`react@^18.2.0` · `axios@^1.7.2` · `recharts@^3.8.1` (optional, for a similarity matrix/heat cells) —
all present, no additions.
