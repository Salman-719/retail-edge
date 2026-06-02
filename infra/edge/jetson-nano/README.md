# Jetson IAIP1 Edge Sampler

This folder contains the production edge package for a Jetson Nano-class device.
The default edge role is **sampling only**:

1. IAIP1 reads camera stream URLs from EEP topology.
2. IAIP1 samples each camera at the configured FPS.
3. IAIP1 writes sampled JPEG frames to cloud S3/MinIO.
4. IAIP1 publishes `vision.frame_ref.v1` events to cloud Redpanda/Kafka.
5. Cloud IAIP2 detector workers read those frame refs and run detection/tracking.

Do not use filesystem frame refs when IAIP2 runs in the cloud; cloud workers
cannot read the Jetson filesystem. Use `IEP1_FRAME_STORAGE=s3`.

## Files

- `docker-compose.iaip1-edge.yml` - runs IAIP1 on the Jetson with host networking.
- `edge.env.example` - production environment template.
- `camera-run.example.json` - direct manual run payload when not using EEP topology.
- `scripts/install-edge-host.sh` - base Docker/host directory setup.
- `systemd/retail-edge-iaip1.service` - optional boot service.

See [docs/deploy-edge.md](../../../docs/deploy-edge.md)
for the full installation and deployment guide.
