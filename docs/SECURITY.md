<!--
  Rubric: S2 — Validation and request constraints (3%), Section 12 of project announcement
-->

# Security and robustness — RetailVision

## 1. Input validation

All EEP REST endpoints use Pydantic v2 models for request validation.

| Endpoint group | Validation applied | Rejection behavior |
|---|---|---|
| POST /auth/login | email format, password min length | 422 |
| POST /stores | store name constraints, slug format | 422 |
| Camera payloads | TODO | TODO |
| Zone payloads | TODO: coordinate bounds, polygon validity | TODO |

## 2. Rate limiting

**Tool:** `slowapi` (SlowAPIMiddleware on the FastAPI app) + `BodySizeLimitMiddleware`.
**Key:** Per-IP, keyed on the leftmost `X-Forwarded-For` hop (EEP sits behind an
ingress; raw `request.client.host` would be the proxy IP for all clients).
**Storage:** Redis-backed in production (shared across the 2 EEP replicas so the
limit is not per-replica). Fails open: if the Redis store is unreachable, the
limiter falls back to in-memory storage and never 503s traffic.

| Limit type | Rate | Env var override | Applies to |
|---|---|---|---|
| Global (all routes) | 120/minute | `RATE_LIMIT_GLOBAL` | Every EEP endpoint |
| Auth login | 10/minute | `RATE_LIMIT_AUTH` | POST /auth/login — brute-force protection |
| Password reset | 5/minute | `RATE_LIMIT_PWRESET` | POST /auth/password-reset |
| Write endpoints | 60/minute | `RATE_LIMIT_WRITE` | POST/PUT/DELETE on resource endpoints |

**Response when exceeded:** HTTP 429 with the canonical error envelope:
```json
{"detail": {"code": "RATE_LIMITED", "error": "Too many requests, slow down"}}
```
Response includes `Retry-After: 60` header (configurable via `RATE_LIMIT_RETRY_AFTER_S`).

**Body size limits** (coarse backstop via `BodySizeLimitMiddleware`):
- Global ceiling: 15 MB (`MAX_REQUEST_BYTES`; checked from `Content-Length` header)
- Per-image upload: 10 MB (`MAX_IMAGE_UPLOAD_BYTES`; re-checked after reading body)
- Per-XML upload: 2 MB (`MAX_XML_UPLOAD_BYTES`)
- Response: HTTP 413 `{"detail": {"code": "PAYLOAD_TOO_LARGE"}}`

## 3. Authentication and authorization

- JWT with refresh tokens (EEP)
- gRPC: TLS + shared-secret auth (edge ↔ cloud)
- Role-based access: TODO (describe roles: owner, member, viewer)

## 4. Network isolation

- Edge-local Redis is loopback-only (not exposed to cloud)
- PostgreSQL and MinIO are not publicly exposed (internal k8s services only)
- EEP is the only public-facing service

## 5. Secrets management

See `docs/DEPLOYMENT.md` Section 3 for full secrets management policy.

## 6. Abuse resistance

**No unauthenticated inference path.** All endpoints that touch vision pipeline
data (cameras, tracking history, analytics, live feed, zones) are behind
`Depends(get_current_user)` JWT auth. There is no public inference endpoint —
the edge inference services (yolo_service, reid_service) are only reachable
via ZMQ unix sockets on the edge device, not exposed over any network interface.

**Payload size limits** (see §2 for values). Both the `Content-Length` header
check (fast rejection before reading body) and a post-read re-check are applied
to prevent a lying `Content-Length` from bypassing the limit.

**List endpoint protection.** `MAX_LIST_ROWS = 1000` is enforced on all
list-returning endpoints. A query that would return 100,000 rows is capped at
1,000 — preventing unbounded response payloads from pathological date ranges
or missing pagination parameters.

**Role-based access.** Super-admin routes (store creation, user management,
audit log) require `is_superuser=True` on the JWT claims. Store-scoped routes
(cameras, zones, analytics) are further restricted to users with explicit
store membership. A valid JWT does not grant access to another tenant's data.

**gRPC edge channel.** The EEP→Edge Agent gRPC link uses TLS + a shared
`GRPC_SHARED_SECRET` for mutual authentication. The edge device rejects any
gRPC call that does not present the correct secret, preventing impersonation
of the EEP by a network attacker who has gained access to the VPN.
