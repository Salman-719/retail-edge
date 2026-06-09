# H1 — Frontend Production Hardening

_The dockerized frontend is the right thing to ship, but as-is it serves plain HTTP, has no
security headers or caching, bakes no environment config, and has no websocket path — so the live
bridge can't even connect from the :3000 build. Close those gaps so the nginx image is genuinely
production-grade behind the cluster's TLS._

## Non-obvious tooling / facts

- Build is multi-stage: `node:20-alpine` → `vite build` → `nginx:alpine` serving `/usr/share/nginx/html`
  ([Dockerfile](../../frontend/Dockerfile)). nginx config is
  [frontend/nginx.conf](../../frontend/nginx.conf): serves the SPA + proxies `/api/` → `eep:8000`
  with `proxy_buffering off` (for MJPEG). No `/ws/`, no headers, no caching.
- `VITE_*` vars bake in **at build time**; the Dockerfile passes none, so anything not present at
  `npm run build` is empty in the image. The app talks to `/api` (relative, nginx-proxied), so
  `VITE_API_URL` is effectively unused in the image — but **`VITE_LIVE_BRIDGE_URL` matters**: DevE2E
  builds `${VITE_LIVE_BRIDGE_URL || 'ws://localhost:8010'}/ws/live/{cam}`
  ([DevE2E.jsx:19,277](../../frontend/src/pages/DevE2E.jsx#L19)), which is wrong in prod.
- The `live_bridge` service listens on `:8010` ([docker-compose.yml:391](../../docker-compose.yml#L391)).
- Deployment is k8s via Helm with **cert-manager** (per ARCHITECTURE) — so production **TLS
  terminates at the ingress**, not in this container. The container nginx stays HTTP behind it.
- Vite emits hash-named assets under `assets/` (safe to cache immutably); `index.html` must not be cached.

## Architectural map

```
frontend/Dockerfile   ARG/ENV VITE_LIVE_BRIDGE_URL (+ VITE_API_URL) before `npm run build`
frontend/nginx.conf   + /ws/ proxy → live_bridge:8010 (Upgrade/Connection)
                      + security headers + gzip + cache-control (immutable assets, no-cache index)
charts/ / ingress     TLS + HSTS at the ingress (cert-manager) — documented, not in-container
```

## Read before implementing

- [frontend/Dockerfile](../../frontend/Dockerfile), [frontend/nginx.conf](../../frontend/nginx.conf)
- [docker-compose.yml:391-400](../../docker-compose.yml#L391) (`live_bridge`)
- the Helm chart ingress in [charts/retailvision](../../charts) (where TLS already terminates)

## Rules (verifiable)

1. **Build-arg env injection** (Dockerfile): declare `ARG VITE_LIVE_BRIDGE_URL` (and `ARG
   VITE_API_URL` for completeness), promote to `ENV` before `npm run build`. Document in compose /
   Helm how to pass them. For prod, `VITE_LIVE_BRIDGE_URL` is the **same-origin wss** (e.g.
   `wss://<host>`) so the browser hits nginx, not `localhost`.
2. **Websocket proxy** (nginx): add a `location /ws/ { proxy_pass http://live_bridge:8010; ... }`
   with `proxy_http_version 1.1`, `proxy_set_header Upgrade $http_upgrade`,
   `proxy_set_header Connection "upgrade"`, `proxy_read_timeout 3600s`, `proxy_buffering off`. So the
   live bridge works from the :3000 image (it does not today).
3. **Security headers** (nginx, on the SPA location): `X-Content-Type-Options nosniff`,
   `X-Frame-Options DENY`, `Referrer-Policy strict-origin-when-cross-origin`, and a **conservative
   baseline CSP** (`default-src 'self'`; allow the API/ws origins, `img-src 'self' data: blob:` for
   floor-plan/Konva, `style-src 'self' 'unsafe-inline'` if Tailwind injects). Mark the CSP as
   "tune against the running app" and verify no console violations before shipping.
4. **Compression**: `gzip on` for `text/css application/javascript application/json image/svg+xml`
   (and brotli if the base image supports it — optional).
5. **Caching**: hash-named assets (`/assets/...`) → `Cache-Control: public, max-age=31536000,
   immutable`; `index.html` → `Cache-Control: no-cache` (so new deploys are picked up). Keep
   `try_files ... /index.html` for SPA routing.
6. **Keep** the existing `/api/` proxy with `proxy_buffering off` (MJPEG) and
   `client_max_body_size 500M` (floor-plan uploads).
7. **TLS**: document that TLS + **HSTS** terminate at the **ingress** (cert-manager); the container
   serves HTTP behind it. For the docker-compose `production-local` variant, optionally add a
   TLS-terminating reverse proxy — note as optional, do not bake certs into the image.

## Acceptance

- The :3000 image, given `VITE_LIVE_BRIDGE_URL`, opens a live websocket through nginx `/ws/` (DevE2E
  live feed connects in a production-style build — it cannot today).
- Response headers show the security headers, gzip, and correct `Cache-Control` (immutable assets,
  no-cache index.html).
- A fresh deploy is reflected immediately (index.html not cached) while assets are long-cached.
- No CSP violations in the console for Analytics (Konva/recharts), Live Monitoring, and floor-plan pages.
- Behind the ingress, the app is served over HTTPS with HSTS; the container itself listens HTTP.

## Hard constraints & anti-patterns

- **Do NOT** bake TLS certs into the frontend image — terminate at the ingress (cluster pattern).
- **Do NOT** set `Cache-Control: immutable` on `index.html` — it strands users on old bundles.
- **Do NOT** ship a CSP you haven't verified against the app — a wrong CSP white-screens it; tune first.
- **Do NOT** hardcode `ws://localhost:8010` for prod — it must be the deployment's same-origin wss
  via build-arg.
- Preserve the MJPEG `proxy_buffering off` and the 500M upload limit.

## Pinned versions

`node:20-alpine` (build) · `nginx:alpine` (serve) · Vite (current frontend toolchain) ·
Helm 3.14 + cert-manager (existing). No app dependency changes.

## Out of scope

Backend TLS/mTLS (edge↔cloud gRPC) is covered by `docs/security/`; this spec is the **frontend**
serving tier only.
