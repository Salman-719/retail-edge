# Build the SPA on the BUILD platform (native, e.g. amd64) — never under QEMU.
# npm/Node crash with "illegal instruction" when emulated for arm64, so pin the
# builder to $BUILDPLATFORM. The output dist/ is static (arch-independent).
FROM --platform=$BUILDPLATFORM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Final image is per-target-arch (nginx:alpine is multi-arch); it only copies the
# pre-built static files — no npm runs under emulation.
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
