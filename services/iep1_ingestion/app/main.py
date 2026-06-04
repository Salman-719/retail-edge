import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()


def _parse_args():
    parser = argparse.ArgumentParser(
        prog="python -m services.iep1_ingestion.app.main",
        description="IEP1 ingestion worker — one process per camera",
    )
    parser.add_argument("--store-id",  required=True,                help="Store identifier")
    parser.add_argument("--camera-id", required=True,                help="Camera identifier")
    parser.add_argument("--rtsp",      required=False, default=None, help="RTSP stream URL")
    parser.add_argument("--video",     default=None,
                        help="Path to a video file. Used instead of --rtsp for dev/test.")
    parser.add_argument("--fps",       type=float, default=5.0,      help="Target FPS (default: 5.0)")
    # --window falls back to WINDOW_SECONDS env var; no hardcoded default.
    _window_env = os.environ.get("WINDOW_SECONDS")
    parser.add_argument("--window",    type=float,
                        default=float(_window_env) if _window_env else None,
                        help="Batch window seconds. Defaults to WINDOW_SECONDS env var.")

    args = parser.parse_args()

    if args.window is None:
        parser.error("--window or WINDOW_SECONDS env var is required")
    if args.window <= 0:
        parser.error("--window must be positive")
    if args.video is None and args.rtsp is None:
        parser.error("one of --rtsp or --video is required")
    if args.video is not None and args.rtsp is not None:
        parser.error("--rtsp and --video are mutually exclusive")

    return args


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()

    logging.getLogger(__name__).info(
        "IEP1 starting  store=%s  camera=%s  window_seconds=%.1f  fps=%.1f  "
        "redis_host=%s  s3_endpoint=%s",
        args.store_id,
        args.camera_id,
        args.window,
        args.fps,
        os.environ.get("REDIS_URL", "").split("@")[-1] or "default",
        os.environ.get("S3_ENDPOINT_URL", ""),
    )

    from services.iep1_ingestion.app.runtime import Iep1Settings, Iep1Runtime
    from services.iep1_ingestion.app.source.rtsp_source import RtspSource, RtspSourceExhausted
    from services.iep1_ingestion.app.source.video_source import VideoFileSource

    settings = Iep1Settings(
        store_id=args.store_id,
        camera_id=args.camera_id,
        target_fps=args.fps,
        batch_window_seconds=args.window,
        s3_bucket=os.environ.get("S3_BUCKET", "retailvision"),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )

    if args.video:
        source = VideoFileSource(
            video_path=args.video,
            target_fps=args.fps,
            start_epoch_ms=int(time.time() * 1000),
        )
    else:
        source = RtspSource(
            rtsp_url=args.rtsp,
            target_fps=args.fps,
            camera_id=args.camera_id,
        )

    try:
        Iep1Runtime(settings, source=source).run()
    except RtspSourceExhausted as exc:
        logging.getLogger(__name__).error("RTSP permanently lost: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
