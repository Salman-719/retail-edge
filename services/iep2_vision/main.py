import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _parse_args():
    parser = argparse.ArgumentParser(
        description="IEP2 vision worker — one process per camera",
    )
    parser.add_argument("--store-id",  required=True,                       help="Store identifier")
    parser.add_argument("--camera-id", required=True,                       help="Camera identifier")
    parser.add_argument("--source",    choices=["video", "redis"],
                        default="video",                                     help="Frame source: video (default) or redis")
    parser.add_argument("--video",     default=None,                        help="Path to video file (required when --source video)")
    parser.add_argument("--start-ms",  type=int, default=0,                 help="Start timestamp offset ms (default: 0)")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()

    if args.source == "video" and not args.video:
        print("error: --video is required when --source is video")
        sys.exit(1)

    # Insert iep2_vision root on path so runtime imports resolve when run as a script.
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)

    from runtime import IEP2Runtime, Iep2Settings

    settings = Iep2Settings(
        store_id=args.store_id,
        camera_id=args.camera_id,
        database_url=os.environ["DATABASE_URL"],
        redis_url=os.environ.get("REDIS_URL",       "redis://localhost:6379/0"),
        s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL", ""),
        s3_access_key=os.environ.get("S3_ACCESS_KEY",   ""),
        s3_secret_key=os.environ.get("S3_SECRET_KEY",   ""),
        s3_bucket=os.environ.get("S3_BUCKET",       "retailvision"),
    )

    runtime = IEP2Runtime(settings)

    if args.source == "redis":
        ctx = runtime.run_from_iep1()
    else:
        ctx = runtime.run(args.video, start_ms=args.start_ms)

    with ctx as stream:
        for _ in stream:
            pass


if __name__ == "__main__":
    main()
