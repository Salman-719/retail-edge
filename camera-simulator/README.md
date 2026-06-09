# RetailVision Camera Simulator

This is a standalone RTSP camera simulator. Run it on a laptop/server that the
edge device can reach on the network. Each video becomes one RTSP camera stream,
and EEP should be configured with those RTSP URLs just like real cameras.

## Quick Start

From the repo root:

```bash
cd camera-simulator
cp .env.example .env
./scripts/start.sh
```

Default streams are Test3 camera 1 and camera 2:

```text
rtsp://<simulator-ip>:8554/test3-cam1
rtsp://<simulator-ip>:8554/test3-cam2
```

Paste those URLs into EEP camera stream URLs for the store. The important part:
`<simulator-ip>` must be reachable from the edge device.

## Files

- `docker-compose.yml` runs MediaMTX plus one FFmpeg publisher container.
- `streams.csv` defines which videos become which RTSP paths.
- `scripts/start.sh` starts the simulator and prints camera URLs.
- `scripts/status.sh` shows container state and publisher logs.
- `scripts/stop.sh` stops the simulator.

## Configure Cameras

Edit `streams.csv`:

```csv
# name,source,path
test3-cam1,/videos/Test3/Cam1.mp4,test3-cam1
test3-cam2,/videos/Test3/Cam2.mp4,test3-cam2
```

The `source` path is inside the publisher container. By default,
`../testing-data` is mounted as `/videos`, so repo videos are available under:

```text
/videos/Test1/Camera1.mp4
/videos/Test1/Camera2.mp4
/videos/Test2/Videos/video_camera1.mp4
/videos/Test3/Cam1.mp4
/videos/Test3/Cam2.mp4
```

The two Test3 publishers wait for one shared wall-clock start boundary, begin
together, and use FFmpeg's infinite input loop. If either publisher exits, the
whole camera group restarts together to avoid silent drift.

To switch back to the Test1 videos:

```bash
sed -i.bak 's|^STREAMS_FILE_HOST=.*|STREAMS_FILE_HOST=./streams.test1.csv|' .env
./scripts/restart.sh
```

## Running On AWS

Yes, this simulator can run on an EC2 instance. Then the camera URLs are:

```text
rtsp://<ec2-public-ip-or-dns>:8554/test3-cam1
rtsp://<ec2-public-ip-or-dns>:8554/test3-cam2
```

For a quick demo, open inbound TCP `8554` on the EC2 security group from the
edge device public IP. Opening `0.0.0.0/0` works technically, but the default
simulator has no RTSP authentication, so do that only briefly for testing.

For a cleaner setup, keep the EC2 security group restricted to the edge egress
IP, or route the edge to the simulator through WireGuard/VPN.

To stream videos from another folder, edit `.env`:

```bash
VIDEO_ROOT=/absolute/path/to/videos
```

Then point `streams.csv` at paths under `/videos`.

## Verify From The Edge Device

Replace the IP with the simulator laptop/server IP:

```bash
sudo k3s kubectl -n retailvision exec deploy/iep1-daemon -- python - <<'PY'
import cv2

urls = [
    "rtsp://192.168.1.45:8554/test3-cam1",
    "rtsp://192.168.1.45:8554/test3-cam2",
]

for url in urls:
    cap = cv2.VideoCapture(url)
    ok, _ = cap.read()
    cap.release()
    print(url, "OK" if ok else "FAILED")
PY
```

If this prints `OK`, the edge can ingest the simulated stream as a real camera.

## If A Stream Does Not Decode

Switch from codec copy to H.264 re-encoding:

```bash
sed -i.bak 's/^PUBLISH_MODE=.*/PUBLISH_MODE=h264/' .env
./scripts/restart.sh
```

This costs more CPU on the simulator machine but is usually more compatible.

## Stop

```bash
./scripts/stop.sh
```
