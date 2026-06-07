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

<!-- TODO: What rate limiting is implemented on the EEP?
     - Per-IP? Per-user? Per-API-key?
     - What is the limit (requests/minute)?
     - What is the response when exceeded (429)?
     - Tool used: FastAPI middleware, nginx, or cloud WAF? -->

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

<!-- TODO: Beyond rate limiting, what prevents abuse?
     - Can an unauthenticated user hit any inference endpoint?
     - Is there payload size validation on video/frame uploads? -->
