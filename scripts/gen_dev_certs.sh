#!/usr/bin/env bash
# Generates a self-signed CA and EEP server certificate for local development.
# Production uses cert-manager or certbot — never use these certs in production.
#
# Output:
#   certs/ca.crt       root CA cert  (committed — distributed to edge devices)
#   certs/ca.key       root CA key   (gitignored — keep secret)
#   certs/server.crt   EEP cert      (committed for convenience in dev)
#   certs/server.key   EEP key       (gitignored — mounted at runtime)
set -euo pipefail

CERTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$CERTS_DIR"

# Root CA
openssl genrsa -out "$CERTS_DIR/ca.key" 4096
openssl req -new -x509 -days 3650 -key "$CERTS_DIR/ca.key" \
  -out "$CERTS_DIR/ca.crt" \
  -subj "/CN=RetailVision Dev CA"

# EEP server cert
openssl genrsa -out "$CERTS_DIR/server.key" 2048
openssl req -new -key "$CERTS_DIR/server.key" \
  -out "$CERTS_DIR/server.csr" \
  -subj "/CN=eep.retailvision.internal"
openssl x509 -req -days 365 \
  -in "$CERTS_DIR/server.csr" \
  -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" -CAcreateserial \
  -out "$CERTS_DIR/server.crt" \
  -extfile <(printf "subjectAltName=DNS:eep.retailvision.internal,DNS:localhost,IP:127.0.0.1")

rm -f "$CERTS_DIR/server.csr" "$CERTS_DIR/ca.srl"

echo "Dev certs generated in $CERTS_DIR/"
echo "  ca.crt     — distribute to edge devices at /etc/retailvision/certs/ca.crt"
echo "  server.crt — mount into EEP container"
echo "  server.key — mount into EEP container (kept secret, gitignored)"
echo ""
echo "Required env vars for EEP:"
echo "  GRPC_SERVER_CERT_PATH=/certs/server.crt"
echo "  GRPC_SERVER_KEY_PATH=/certs/server.key"
echo "  AGENT_SECRET=<generate with: openssl rand -hex 32>"
echo ""
echo "Required env vars for Edge Agent:"
echo "  GRPC_CA_CERT_PATH=/etc/retailvision/certs/ca.crt"
echo "  AGENT_SECRET=<same value as EEP>"
