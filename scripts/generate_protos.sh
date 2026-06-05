#!/bin/bash
# scripts/generate_protos.sh
# Regenerates gRPC stubs for all services from proto/*.proto.
# Run via: bash scripts/generate_protos.sh  (or: make proto)
# After generation, applies the package import fix that protoc gets wrong.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Sync service proto dirs from canonical source ─────────────────────────────
mkdir -p services/eep/proto services/edge_agent/proto services/iep1_ingestion/proto
cp proto/agent.proto        services/eep/proto/agent.proto
cp proto/agent.proto        services/edge_agent/proto/agent.proto
cp proto/iep1_control.proto services/iep1_ingestion/proto/iep1_control.proto
cp proto/iep1_control.proto services/edge_agent/proto/iep1_control.proto

# ── EEP: agent stubs ──────────────────────────────────────────────────────────
python -m grpc_tools.protoc \
  -I proto \
  --python_out=services/eep/app/grpc_generated \
  --grpc_python_out=services/eep/app/grpc_generated \
  proto/agent.proto

sed -i 's/^import agent_pb2/from app.grpc_generated import agent_pb2/' \
  services/eep/app/grpc_generated/agent_pb2_grpc.py
sed -i '1s/^/# AUTO-GENERATED — see proto\/agent.proto. Regenerate via: make proto\n/' \
  services/eep/app/grpc_generated/agent_pb2_grpc.py

# ── Edge Agent: agent stubs ───────────────────────────────────────────────────
python -m grpc_tools.protoc \
  -I proto \
  --python_out=services/edge_agent/app/grpc_generated \
  --grpc_python_out=services/edge_agent/app/grpc_generated \
  proto/agent.proto

sed -i 's/^import agent_pb2/from services.edge_agent.app.grpc_generated import agent_pb2/' \
  services/edge_agent/app/grpc_generated/agent_pb2_grpc.py
sed -i '1s/^/# AUTO-GENERATED — see proto\/agent.proto. Regenerate via: make proto\n/' \
  services/edge_agent/app/grpc_generated/agent_pb2_grpc.py

# ── Edge Agent: iep1_control stubs (client) ───────────────────────────────────
python -m grpc_tools.protoc \
  -I proto \
  --python_out=services/edge_agent/app/grpc_generated \
  --grpc_python_out=services/edge_agent/app/grpc_generated \
  proto/iep1_control.proto

sed -i 's/^import iep1_control_pb2/from services.edge_agent.app.grpc_generated import iep1_control_pb2/' \
  services/edge_agent/app/grpc_generated/iep1_control_pb2_grpc.py

# ── IEP1: iep1_control stubs (server) ────────────────────────────────────────
mkdir -p services/iep1_ingestion/app/grpc_generated
python -m grpc_tools.protoc \
  -I proto \
  --python_out=services/iep1_ingestion/app/grpc_generated \
  --grpc_python_out=services/iep1_ingestion/app/grpc_generated \
  proto/iep1_control.proto

sed -i 's/^import iep1_control_pb2/from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2/' \
  services/iep1_ingestion/app/grpc_generated/iep1_control_pb2_grpc.py

touch services/iep1_ingestion/app/grpc_generated/__init__.py

echo "Proto generation complete."
