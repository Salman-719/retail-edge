.PHONY: proto cloud-eks-deploy camera-sim-up camera-sim-down camera-sim-status

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

cloud-eks-deploy:
	bash scripts/deploy-cloud-eks-from-scratch.sh

camera-sim-up:
	bash camera-simulator/scripts/start.sh

camera-sim-down:
	bash camera-simulator/scripts/stop.sh

camera-sim-status:
	bash camera-simulator/scripts/status.sh
