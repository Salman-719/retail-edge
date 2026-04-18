# RetailVision AI — Plans Index

**Project:** EECE503N / EECE798N — AI Engineering Final Project
**Last Updated:** 2026-04-18

Two equally authoritative views over the same work:

- **Per-service plans** (`services/`) — one document per IEP / EEP / frontend / infra, covering that component's full lifecycle across all milestones. **Start here when working on a specific service.**
- **Milestone plans** (`milestones/`) — the phased delivery view. **Start here to plan sequence and dependencies.**

---

## Per-Service Plans

| Service | Plan | Scope |
|---------|------|-------|
| **EEP** | [EEP_plan.md](services/EEP_plan.md) | Gateway, auth, orchestrator, proxy routes, relational store |
| **IEP1** | [IEP1_Ingestion_plan.md](services/IEP1_Ingestion_plan.md) | Video upload, frame quality, chunking, RTSP |
| **IEP2** | [IEP2_Vision_plan.md](services/IEP2_Vision_plan.md) | Detection, tracking, ReID, cross-camera, MLOps |
| **IEP3** | [IEP3_Alerts_plan.md](services/IEP3_Alerts_plan.md) | Alert rules, evaluation engine, persistence |
| **IEP4** | [IEP4_Analytics_plan.md](services/IEP4_Analytics_plan.md) | Aggregation, heatmaps, flow, POS, batch |
| **IEP5** | [IEP5_Agent_plan.md](services/IEP5_Agent_plan.md) | LLM client, tools, reports, hallucination detection |
| **Frontend** | [Frontend_plan.md](services/Frontend_plan.md) | Onboarding, live monitoring, analytics, agent UI |
| **Infra** | [Infra_plan.md](services/Infra_plan.md) | DB, Docker, CI, monitoring, K8s, tests, docs, demo |

Each per-service plan contains: contract (endpoints + schemas), current status, remaining tasks with file paths, evaluation criteria, key files reference, re-iteration triggers.

---

## Milestone Plans (phased delivery)

| # | Milestone | Duration | Status | Completion |
|---|-----------|----------|--------|------------|
| M1 | [Project Setup & Infrastructure](milestones/M1_Project_Setup_Infrastructure.md) | 1 week | In Progress | ~85% |
| M2 | [Store Onboarding & Frontend](milestones/M2_Store_Onboarding_Frontend.md) | 2 weeks | In Progress | ~80% |
| M3 | [Vision Pipeline (Single Camera)](milestones/M3_Vision_Pipeline_Single_Camera.md) | 2–3 weeks | In Progress | ~50% |
| M4 | [Multi-Camera & Core E2E](milestones/M4_Multi_Camera_Core_E2E.md) | 2 weeks | Not Started | ~15% |
| M5 | [Batch Analytics Pipeline](milestones/M5_Batch_Analytics_Pipeline.md) | 1.5 weeks | Not Started | ~10% |
| M6 | [AI Insights Agent](milestones/M6_AI_Insights_Agent.md) | 1.5 weeks | Not Started | ~5% |
| M7 | [MLOps Pipeline](milestones/M7_MLOps_Pipeline.md) | 1 week | Not Started | 0% |
| M8 | [Monitoring, Security & Observability](milestones/M8_Monitoring_Security_Observability.md) | 1 week | Partial | ~40% |
| M9 | [Frontend Dashboard Completion](milestones/M9_Frontend_Dashboard_Completion.md) | 1.5 weeks | Not Started | ~35% |
| M10 | [Cloud Deployment & Kubernetes](milestones/M10_Cloud_Deployment_Kubernetes.md) | 1.5 weeks | Not Started | 0% |
| M11 | [Integration, Docs & Demo](milestones/M11_Integration_Docs_Demo.md) | 1 week | Not Started | ~5% |

**Total estimated: 15–17 weeks**

---

## Milestone ↔ Service Matrix

Which services are touched by which milestone:

|  | EEP | IEP1 | IEP2 | IEP3 | IEP4 | IEP5 | Frontend | Infra |
|--|-----|------|------|------|------|------|----------|-------|
| M1 | x | x | x | x | x | x |  | x |
| M2 | x |  |  |  |  |  | x |  |
| M3 |  | x | x |  |  |  |  |  |
| M4 | x |  | x | x |  |  |  |  |
| M5 |  |  |  |  | x |  |  |  |
| M6 |  |  |  |  |  | x |  |  |
| M7 |  |  | x |  |  |  |  | x |
| M8 | x | x | x | x | x | x |  | x |
| M9 | x |  |  |  |  |  | x |  |
| M10 |  |  |  |  |  |  |  | x |
| M11 | x | x | x | x | x | x | x | x |

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

**Critical path:** M1 → M3 → M4 → M5 → M6 → M9 → M10 → M11 (~12–13 weeks)

---

## How to Use These Plans

**Service-first (recommended when working on one component):**
1. Open that service's plan under `services/`.
2. Read the Contract + Current Status tables.
3. Work through Remaining Tasks in order.
4. Run Evaluation Criteria as a checklist.

**Milestone-first (recommended for sprint planning):**
1. Open the current milestone doc under `milestones/`.
2. Check Current Status for what's remaining.
3. For each item, jump to the relevant per-service plan for the deeper task breakdown.
4. Run milestone Evaluation Criteria before moving on.

---

## Reference Document

[RetailVision_AI_Implementation_Plan.docx](RetailVision_AI_Implementation_Plan.docx) — Original master plan with learning outcomes and technology references.
