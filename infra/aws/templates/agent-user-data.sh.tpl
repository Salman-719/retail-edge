#!/bin/bash
# EC2 user-data for a k3s AGENT node (scale-out for more stores). Joins the
# server using the shared token; add-ons live on the server only.
set -euxo pipefail
until curl -skf "https://${server_ip}:6443/ping" >/dev/null; do
  echo "waiting for k3s server ${server_ip}..."; sleep 5
done
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_VERSION="${k3s_version}" \
  K3S_URL="https://${server_ip}:6443" \
  K3S_TOKEN="${k3s_token}" \
  sh -s - --node-name "cloud-agent-${index}"
