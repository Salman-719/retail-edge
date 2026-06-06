<!--
  Rubric: T4 — EEP orchestration logic (5%)
  This document proves EEP does real orchestration, not just CRUD.
-->

# EEP — control plane service

**Location:** `services/eep/`
**Runs on:** Cloud (one instance)
**Exposes:** REST :8000, gRPC :50051 TLS

## 1. Role and motivation

EEP is the management brain. It is NOT a thin CRUD API — it actively orchestrates
the edge pipeline, enforces business schedules, and is the only public-facing
service in the system.

## 2. Orchestration logic

### 2.1 Camera lifecycle management
- EEP receives camera schedule configuration (days, times) from store operators
- APScheduler runs a loop that evaluates all camera schedules
- At scheduled start time: EEP sends gRPC `StartCamera` to the Edge Agent for that store
- Edge Agent translates `StartCamera` into a `kubectl apply` on k3s, spawning an IEP2 Deployment
- At scheduled stop time: EEP sends gRPC `StopCamera`, Edge Agent tears down the IEP2 Deployment

This is real orchestration: EEP is actively managing the lifecycle of edge compute resources.

### 2.2 Conditional and parallel interactions
<!-- TODO: Does EEP ever call multiple IEPs in parallel or conditionally?
     E.g., does it conditionally trigger alerts based on IEP3 output?
     Document any non-trivial control flow here. -->

## 3. REST API routers

| Router | Purpose | Orchestration logic |
|---|---|---|
| `auth` | JWT login, refresh, registration, invite | Token lifecycle |
| `stores` | Create/manage stores (multi-tenant root) | Store isolation |
| `config` / `draft` | Floor plan, zones, cameras, calibration | Versioned draft → publish |
| `members` | Org members and roles | Invite, role enforcement |
| `employees` / `shifts` | Staff records, shift patterns | Schedule assignment |
| `schedules` | Per-camera active windows | Drives Start/StopCamera via APScheduler |
| `audit` | Audit log of privileged actions | Write-only append log |
| `settings` | Store/org settings | - |
| `debug` / `dev_pipeline` | Dev-only routes (DEBUG_MODE gated) | Drive pipeline manually |

## 4. gRPC server

- Listens on `:50051` with TLS
- Edge agents dial OUT to EEP (edge initiates connection; avoids NAT issues)
- Bidirectional streaming: EEP pushes StartCamera/StopCamera commands down the open stream
- Auth: shared secret validated on connection

## 5. Input validation and constraints

- All request bodies validated by Pydantic v2 models
- Rate limits: see `docs/SECURITY.md` §2
- Schema constraints: TODO (list key validation rules)

## 6. Error handling

| Scenario | Behavior |
|---|---|
| gRPC call to edge agent fails | TODO: retry with backoff, alert if edge offline |
| Edge agent disconnects | TODO: how EEP detects and handles |
| APScheduler job throws | TODO: logged, retried on next tick? |
| DB write fails | TODO |
