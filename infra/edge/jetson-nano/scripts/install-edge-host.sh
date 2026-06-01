#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y ca-certificates curl git docker.io

if ! docker compose version >/dev/null 2>&1; then
  sudo apt-get install -y docker-compose-plugin || sudo apt-get install -y docker-compose
fi

sudo systemctl enable --now docker
sudo usermod -aG docker "${SUDO_USER:-$USER}" || true

sudo mkdir -p /etc/retail-edge/ca /var/lib/retail-edge/frame-cache /opt/retail-edge
sudo chown -R "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" /var/lib/retail-edge /opt/retail-edge

cat <<'MSG'
Base host setup is done.

Next:
1. Clone or copy this repo into /opt/retail-edge.
2. Copy infra/edge/jetson-nano/edge.env.example to /etc/retail-edge/iaip1-edge.env.
3. Edit /etc/retail-edge/iaip1-edge.env with real EEP, Kafka, S3, and store values.
4. Log out and back in so Docker group membership applies.
MSG
