FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# Vite bakes VITE_* at BUILD time. Pass via --build-arg (docker-compose `build.args`
# or Helm). In production VITE_LIVE_BRIDGE_URL MUST be the deployment's same-origin
# wss (e.g. wss://app.example.com) so the browser opens the live websocket through
# nginx /ws/ — NOT ws://localhost:8010. VITE_API_URL is effectively unused (the app
# talks to the relative /api, nginx-proxied) but declared for completeness.
ARG VITE_API_URL=""
ARG VITE_LIVE_BRIDGE_URL=""
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_LIVE_BRIDGE_URL=$VITE_LIVE_BRIDGE_URL
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
