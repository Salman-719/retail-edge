# Main Vision Debug (DevE2E) — Redesign & Deep Debug

_The end-to-end tester is information-rich but unreadable: six stacked sub-panels per camera, the
core event (cross-camera reconciliation) has no spatial view, and identity has no through-line.
Rebuild it around one real floor map, progressive disclosure, and consistent identity — then make
IEP3 actually explain its merge decisions instead of only showing the final positions._

---

## Decisions (locked)

| Decision | Choice |
|---|---|
| Centerpiece | A **unified real floor-plan view**: zones + every camera's IEP2 foot-points (color per camera) + IEP3 reconciled global dots (color per global), via the shared `worldToPixel`. |
| Density | **Progressive disclosure** — default shows feeds + the map + IEP3 summary; raw tables / track-maps / foot-point snapshots / replay live behind expanders. |
| Identity | **Coherent across the whole screen** — one color+number per `global_id` in feeds, map, and tables; explicit **local→global** linkage. |
| Deep debug | **Build the IEP3 reconciliation trace** (camera graph, spatial votes, ReID cosines, selection scores) and render the "why merged" panels. |
| Trace storage | **A capped dev-only table** (survives Stop → works in replay/post-mortem). |
| Trace gating | **Off in production**; enabled per-run via a Redis toggle (like the existing `inference:device`). |
| Deep panels (v1) | All four: local→global mapping, per-pair merge decisions, ReID similarity, selection-score breakdown. |

## What IEP3 computes (grounded)

`reconciler.py`: (1) camera graph of overlapping pairs → (2) **spatial voting** per pair
(`spatial_voter.vote_camera_pair` → confirmed/ambiguous sets with `vote_rate`, `votes`, `co_visible`)
→ (3) **ReID appearance fallback** (cosine vs `reid_fallback_threshold`) → (4) **selection**
(`_selection_score`). Persisted today: `global_local_mapping` (local↔global↔camera),
`global_tracking_history` (`selection_score`, `source_camera`). **Not persisted:** the graph, the
vote results, the cosines, the score components — those exist only in-memory per batch. The trace
captures them.

## Subpart map

| Spec | Scope |
|---|---|
| [VD1-iep3-recon-trace.md](VD1-iep3-recon-trace.md) | IEP3 emits a per-batch reconciliation trace → capped dev table + dev endpoint, Redis-gated. |
| [VD2-frontend-redesign.md](VD2-frontend-redesign.md) | Unified floor map, progressive disclosure, identity coherence, stage-based layout. Uses existing data. |
| [VD3-deep-debug-panels.md](VD3-deep-debug-panels.md) | The four deep panels, consuming VD1's trace + `global_local_mapping`. |

## Constraints carried in

- This screen is **admin-gated and ships to prod** ([A4](../admin-rbac/A4-devtools-gating.md),
  [A5](../admin-rbac/A5-frontend.md)); the trace must never run in a normal production pipeline.
- Reuse the shared `worldToPixel` (`px = world*ppm + origin`) — same helper as zones/heatmap/live.
- The live-bridge frames already carry within-camera `reid_sim`/`reid_matched` per detection — reuse.

## Implementation order

VD1 → VD3 (panels need the trace); VD2 in parallel (uses existing data). VD2 is the readability win
even before VD1/VD3 land.
