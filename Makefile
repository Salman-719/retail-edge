.PHONY: proto

# Regenerate gRPC stubs from proto/agent.proto and sync service proto dirs.
# On Unix: creates symlinks. On Windows (Git Bash / WSL): copies the file.
# Run this after any change to proto/agent.proto.
proto:
ifeq ($(OS),Windows_NT)
	copy /Y proto\agent.proto services\eep\proto\agent.proto
	copy /Y proto\agent.proto services\edge_agent\proto\agent.proto
else
	ln -sf ../../proto/agent.proto services/eep/proto/agent.proto
	ln -sf ../../proto/agent.proto services/edge_agent/proto/agent.proto
endif
	bash scripts/generate_protos.sh
