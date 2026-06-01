# Production Deployment: Jetson Edge Sampling to Cloud Vision

This guide describes the production deployment shape for stores where cameras are
local to the store and the main platform runs in the cloud or on a store server.

The recommended first production split is:

```text
Jetson edge device
  IAIP1 ingestion/sampling
  camera health reporting
  sampled frame upload
  frame-ref event publishing

Cloud or store server
  EEP control plane
  Redpanda/Kafka
  MinIO/S3
  Postgres/pgvector
  IAIP2 detector workers
  IEP3 reconciliation
  frontend/analytics
```

For a classic Jetson Nano, run IAIP1 only. For a Jetson Orin Nano, IAIP2 can be
moved to the edge later, but only after TensorRT model packaging and load tests.

## What Runs Where

**Jetson Nano-class edge**

- Reads RTSP/HTTP/file camera streams with OpenCV.
- Samples frames at `1-2 fps` per camera by default.
- Writes JPEG frames to S3/MinIO with keys like:
  `vision-frames/{run_id}/{camera_id}/frame_000000000001.jpg`.
- Publishes Kafka events to `vision.frame_ref.v1`.
- Reports camera health back to EEP.

**Cloud/store server**

- EEP owns stores, sections, camera configs, stream URLs, and calibrations.
- Redpanda/Kafka receives frame refs from edge.
- IAIP2 detector workers consume frame refs, read S3 frames, detect persons,
  track local IDs, extract ReID embeddings, and persist local observations.
- IEP3 consumes batch completion/reconciliation state, assigns global IDs, and
  persists the global gallery.

## Capacity Guidance

Use these as starting budgets, then measure on real streams:

| Device | Recommended role | Practical camera count |
| --- | --- | --- |
| Jetson Nano 4GB | IAIP1 sampling only | 4-8 cameras at 1-2 fps JPEG sampling |
| Jetson Orin Nano 8GB | IAIP1 + optional light IAIP2 | 2-3 detector cameras safely, 4 aggressively |
| Store server / GPU cloud | IAIP2 + IEP3 | Scale by GPU pods and Kafka lag |

For 30-camera stores, do not put all detection on one Jetson. Use multiple edge
samplers or one stronger store server, and keep IAIP2 detector workers scalable.
If bandwidth is limited, lower `IEP1_AUTO_START_SAMPLE_RATE_FPS`, crop at the
camera where possible, or use lower-resolution secondary streams.

## Cloud Prerequisites

1. Deploy the cloud/store services.

   ```bash
   kubectl apply -k infra/k8s
   ```

2. Expose these endpoints to the Jetson network:

   - `EEP_BASE_URL`, for topology and camera health.
   - `VISION_EVENT_BOOTSTRAP_SERVERS`, for Redpanda/Kafka.
   - `S3_ENDPOINT_URL`, for sampled frame upload.

3. Create Kafka topics:

   - `vision.frame_ref.v1`
   - `vision.local_track_observed.v1`
   - `vision.global_identity_observed.v1`

4. Give the Jetson a restricted credential set:

   - Kafka: produce-only to `vision.frame_ref.v1`.
   - S3: write/read only under `vision-frames/`.
   - EEP: internal token only for topology read and camera health write.

5. In EEP, configure active camera topology:

   - Store
   - Section
   - Physical camera
   - Camera config with `stream_url`
   - Current calibration

For v1, one section equals one global ReID group.

## Jetson Host Installation

Install JetPack/L4T first using NVIDIA's official flow for your board. For
sampling-only IAIP1, GPU containers are not required. If you later run IAIP2 on
Orin, install and configure NVIDIA Container Toolkit too.

On the Jetson:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone <your-repo-url> /opt/retail-edge
cd /opt/retail-edge
sudo infra/edge/jetson-nano/scripts/install-edge-host.sh
```

Log out and back in so the Docker group change applies.

Verify Docker:

```bash
docker --version
docker compose version || docker-compose --version
```

Optional GPU-container verification for Orin/edge IAIP2 later:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## Jetson Configuration

Create the edge environment file:

```bash
sudo cp /opt/retail-edge/infra/edge/jetson-nano/edge.env.example /etc/retail-edge/iaip1-edge.env
sudo nano /etc/retail-edge/iaip1-edge.env
```

Set these values:

```bash
IEP1_AUTO_START_STORE_ID=<eep-store-uuid>
IEP1_AUTO_START_RUN_ID=edge-<store-code>
IEP1_AUTO_START_SAMPLE_RATE_FPS=2.0
IEP1_STREAM_RETRY_SECONDS=10
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp

EEP_BASE_URL=https://eep.your-domain.com
VISION_INTERNAL_TOKEN=<token-from-cloud-secret>

EVENT_BUS_BACKEND=kafka
VISION_EVENT_BOOTSTRAP_SERVERS=redpanda.your-domain.com:9094
VISION_KAFKA_SECURITY_PROTOCOL=SASL_SSL
VISION_KAFKA_SASL_MECHANISM=SCRAM-SHA-256
VISION_KAFKA_SASL_USERNAME=edge-camera-writer
VISION_KAFKA_SASL_PASSWORD=<secret>
VISION_KAFKA_CA_FILE=/etc/retail-edge/ca/cloud-kafka-ca.pem

IEP1_FRAME_STORAGE=s3
S3_ENDPOINT_URL=https://minio.your-domain.com
S3_BUCKET=retailvision
S3_ACCESS_KEY=edge-camera-writer
S3_SECRET_KEY=<secret>
```

If your Kafka or object store uses a private CA:

```bash
sudo cp cloud-kafka-ca.pem /etc/retail-edge/ca/cloud-kafka-ca.pem
sudo cp object-store-ca.pem /etc/retail-edge/ca/object-store-ca.pem
```

Then set:

```bash
AWS_CA_BUNDLE=/etc/retail-edge/ca/object-store-ca.pem
```

## Start IAIP1 on the Jetson

From `/opt/retail-edge`:

```bash
docker compose \
  -f infra/edge/jetson-nano/docker-compose.iaip1-edge.yml \
  --env-file /etc/retail-edge/iaip1-edge.env \
  up -d --build
```

Check health:

```bash
curl http://127.0.0.1:8001/health
```

Check the auto-started run:

```bash
curl http://127.0.0.1:8001/runs/edge-<store-code>
```

Follow logs:

```bash
docker compose \
  -f infra/edge/jetson-nano/docker-compose.iaip1-edge.yml \
  --env-file /etc/retail-edge/iaip1-edge.env \
  logs -f iaip1_ingestion
```

## Optional systemd Boot Service

Install the provided service:

```bash
sudo cp /opt/retail-edge/infra/edge/jetson-nano/systemd/retail-edge-iaip1.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now retail-edge-iaip1
```

Check it:

```bash
systemctl status retail-edge-iaip1
journalctl -u retail-edge-iaip1 -f
```

## Manual Run Without EEP Topology

Use this only for smoke tests. Edit:

```bash
cp infra/edge/jetson-nano/camera-run.example.json /tmp/camera-run.json
nano /tmp/camera-run.json
```

Start the run:

```bash
curl -X POST http://127.0.0.1:8001/streams/runs \
  -H "Content-Type: application/json" \
  -d @/tmp/camera-run.json
```

For production, prefer EEP topology with:

```bash
curl -X POST "http://127.0.0.1:8001/stores/<store_uuid>/streams/runs?sample_rate_fps=2.0"
```

or set `IEP1_AUTO_START_STORE_ID`.

## What the Cloud Receives

For each sampled frame IAIP1 publishes:

```json
{
  "event_type": "vision.frame_ref.v1",
  "store_id": "...",
  "version_id": "...",
  "section_id": "...",
  "camera_id": "...",
  "camera_config_id": "...",
  "source_ts": "2026-05-30T12:00:00.000Z",
  "sequence": 42,
  "frame_ref": {
    "uri": "s3://retailvision/vision-frames/run/camera/frame_000000000042.jpg",
    "width": 1920,
    "height": 1080
  }
}
```

IAIP2 cloud workers must have S3 credentials that can read these URIs.

## Production Tuning

Start conservative:

```bash
IEP1_AUTO_START_SAMPLE_RATE_FPS=2.0
```

Use camera secondary streams when available:

```text
rtsp://user:pass@camera-ip:554/secondary
```

Recommended starting points:

- 1080p, 2 fps, 4 cameras: safe for Nano-class sampling.
- 720p, 2 fps, 8 cameras: usually practical if network and JPEG encode are stable.
- 30 cameras: split across edge devices or use a store server; do not rely on one Nano.

If cloud lag rises:

1. Lower sample FPS.
2. Use lower-resolution camera substreams.
3. Add IAIP2 detector pods/GPU capacity.
4. Add a second edge sampler for camera groups.

## Verification Checklist

On Jetson:

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8001/runs/$IEP1_AUTO_START_RUN_ID
docker logs retail-edge-iaip1-edge-iaip1_ingestion-1 --tail=100
```

In cloud:

- S3 has new `vision-frames/...jpg` objects.
- Redpanda has messages in `vision.frame_ref.v1`.
- EEP camera health shows `online`.
- IAIP2 worker logs show frame refs being consumed.
- Postgres `tracking_history` receives rows.
- IEP3 creates/updates global identities.

## Security Rules

- Never commit RTSP URLs with real credentials.
- Do not expose camera RTSP directly to the internet.
- Use VPN/private networking where possible.
- Use TLS/SASL for Kafka outside a private lab network.
- Use restricted S3 credentials for edge writers.
- Rotate `VISION_INTERNAL_TOKEN`, Kafka, and S3 credentials per store/device.

## Current Limitation

This repo now has the edge sampler package and production event contracts, but
the full live cloud path still needs a real deployment validation:

```text
Jetson IAIP1 -> cloud Kafka -> IAIP2 worker -> Postgres -> IEP3 -> EEP/frontend
```

The local demo upload path has been verified; the live Kafka path should be the
next deployment acceptance test.
