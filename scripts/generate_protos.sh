#!/bin/bash
# scripts/generate_protos.sh
# Regenerates gRPC stubs for all services from proto/agent.proto.
# Run via: bash scripts/generate_protos.sh  (or: make proto)
# After generation, applies the package import fix that protoc gets wrong.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Sync service proto dirs from canonical source (idempotent copy).
# On Linux/Mac with developer symlinks these are already linked; the copy is a no-op.
# On Windows (Git Bash / WSL) the copy keeps them in sync.
cp proto/agent.proto services/eep/proto/agent.proto
cp proto/agent.proto services/edge_agent/proto/agent.proto

# ── EEP stubs ────────────────────────────────────────────────────────────────
python -m grpc_tools.protoc \
  -I proto \
  --python_out=services/eep/app/grpc_generated \
  --grpc_python_out=services/eep/app/grpc_generated \
  proto/agent.proto

# Fix protoc-generated absolute import — broken inside the grpc_generated package.
# protoc emits:  import agent_pb2 as agent__pb2
# Required:      from app.grpc_generated import agent_pb2 as agent__pb2
sed -i 's/^import agent_pb2/from app.grpc_generated import agent_pb2/' \
  services/eep/app/grpc_generated/agent_pb2_grpc.py

# ── Edge Agent stubs ──────────────────────────────────────────────────────────
python -m grpc_tools.protoc \
  -I proto \
  --python_out=services/edge_agent/app/grpc_generated \
  --grpc_python_out=services/edge_agent/app/grpc_generated \
  proto/agent.proto

sed -i 's/^import agent_pb2/from app.grpc_generated import agent_pb2/' \
  services/edge_agent/app/grpc_generated/agent_pb2_grpc.py

echo "Proto generation complete."
