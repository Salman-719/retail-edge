import argparse
import logging
import os

from dotenv import load_dotenv

load_dotenv()


def _parse_args():
    parser = argparse.ArgumentParser(
        prog="python -m services.iep1_ingestion.app.main",
        description="IEP1 ingestion worker — one process per camera",
    )
    parser.add_argument("--store-id",  required=True,       help="Store identifier")
    parser.add_argument("--camera-id", required=True,       help="Camera identifier")
    parser.add_argument("--rtsp",      required=True,       help="RTSP stream URL")
    parser.add_argument("--fps",       type=float, default=5.0,  help="Target FPS (default: 5.0)")
    parser.add_argument("--window",    type=float, default=60.0, help="Batch window seconds (default: 60.0)")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()

    from services.iep1_ingestion.app.runtime import Iep1Settings, Iep1Runtime

    settings = Iep1Settings(
        store_id=args.store_id,
        camera_id=args.camera_id,
        rtsp_url=args.rtsp,
        target_fps=args.fps,
        batch_window_seconds=args.window,
        s3_bucket=os.environ.get("S3_BUCKET", "retailvision"),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )

    Iep1Runtime(settings).run()


if __name__ == "__main__":
    main()
