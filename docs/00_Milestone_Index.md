# RetailVision AI — Milestone Plans Index

**Project:** EECE503N / EECE798N — AI Engineering Final Project
**Last Updated:** 2026-04-08

---

## Progress Overview

| # | Milestone | Duration | Status | Completion |
|---|-----------|----------|--------|------------|
| M1 | [Project Setup & Infrastructure](M1_Project_Setup_Infrastructure.md) | 1 week | In Progress | ~85% |
| M2 | [Store Onboarding & Frontend](M2_Store_Onboarding_Frontend.md) | 2 weeks | In Progress | ~80% |
| M3 | [Vision Pipeline (Single Camera)](M3_Vision_Pipeline_Single_Camera.md) | 2-3 weeks | In Progress | ~50% |
| M4 | [Multi-Camera & Core E2E](M4_Multi_Camera_Core_E2E.md) | 2 weeks | Not Started | ~15% |
| M5 | [Batch Analytics Pipeline](M5_Batch_Analytics_Pipeline.md) | 1.5 weeks | Not Started | ~10% |
| M6 | [AI Insights Agent](M6_AI_Insights_Agent.md) | 1.5 weeks | Not Started | ~5% |
| M7 | [MLOps Pipeline](M7_MLOps_Pipeline.md) | 1 week | Not Started | 0% |
| M8 | [Monitoring, Security & Observability](M8_Monitoring_Security_Observability.md) | 1 week | Partial | ~40% |
| M9 | [Frontend Dashboard Completion](M9_Frontend_Dashboard_Completion.md) | 1.5 weeks | Not Started | ~35% |
| M10 | [Cloud Deployment & Kubernetes](M10_Cloud_Deployment_Kubernetes.md) | 1.5 weeks | Not Started | 0% |
| M11 | [Integration, Docs & Demo](M11_Integration_Docs_Demo.md) | 1 week | Not Started | ~5% |

**Total estimated: 15-17 weeks**

---

## Dependency Graph

```
M1 ──> M2 ──┐
             ├──> M4 ──> M5 ──> M6
M1 ──> M3 ──┘         │       │
       │               v       v
       └──> M7         M8     M9
                        │
                        v
                       M10
                        │
                        v
                       M11 (depends on ALL)
```

**Parallelizable:**
- M2 and M3 can run in parallel (frontend + vision are independent until M4)
- M7 can start after M3, in parallel with M4/M5
- M8 can start after M4, in parallel with M5/M6

**Critical path:** M1 -> M3 -> M4 -> M5 -> M6 -> M9 -> M10 -> M11 (~12-13 weeks)

---

## How to Use These Plans

Each milestone document contains:

1. **Current Status** — table showing what's done vs remaining
2. **Implementation Tasks** — detailed file-level instructions with code patterns
3. **Evaluation Criteria** — pass/fail checklist (must all pass before moving on)
4. **Re-iteration Triggers** — what to do when things go wrong

**Workflow:**
1. Open the milestone doc
2. Check status table for what's remaining
3. Follow implementation tasks in order
4. Run evaluation criteria as a checklist
5. If any criterion fails, check re-iteration triggers
6. Mark milestone complete, move to next

---

## Reference Document

[RetailVision_AI_Implementation_Plan.docx](RetailVision_AI_Implementation_Plan.docx) — Original master plan with learning outcomes and technology references.
