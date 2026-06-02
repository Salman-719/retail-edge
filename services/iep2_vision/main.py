import argparse
import asyncio
import logging
import os
import sys
import uuid as _uuid

from dotenv import load_dotenv

load_dotenv()


def _uuid_arg(value: str) -> str:
    try:
        _uuid.UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a valid UUID: {value!r}")
    return value


def _parse_args():
    parser = argparse.ArgumentParser(
        description="IEP2 vision worker — one process per camera",
    )
    parser.add_argument("--store-id",          required=True,  type=_uuid_arg, help="Store identifier (UUID)")
    parser.add_argument("--camera-id",         required=True,                  help="Camera identifier")
    parser.add_argument("--camera-config-id",  default=None,   type=_uuid_arg,
                        help="UUID of the camera_configs row. Required for floor projection. "
                             "If omitted, floor_x/floor_y/zone_id are stored as NULL.")
    parser.add_argument("--source",            choices=["video", "redis"],
                        default="video",                                        help="Frame source: video (default) or redis")
    parser.add_argument("--video",             default=None,                   help="Path to video file (required when --source video)")
    parser.add_argument("--start-ms",          type=int, default=0,            help="Start timestamp offset ms (default: 0)")
    return parser.parse_args()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()

    if args.source == "video" and not args.video:
        print("error: --video is required when --source is video")
        sys.exit(1)

    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)

    from runtime import IEP2Runtime, Iep2Settings

    settings = Iep2Settings(
        store_id=args.store_id,
        camera_id=args.camera_id,
        camera_config_id=args.camera_config_id,
        database_url=os.environ["DATABASE_URL"],
        redis_url=os.environ.get("REDIS_URL",         "redis://localhost:6379/0"),
        s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL",  ""),
        s3_access_key=os.environ.get("S3_ACCESS_KEY",    ""),
        s3_secret_key=os.environ.get("S3_SECRET_KEY",    ""),
        s3_bucket=os.environ.get("S3_BUCKET",        "retailvision"),
    )

    runtime = IEP2Runtime(settings)

    if args.source == "redis":
        ctx = runtime.run_from_iep1()
    else:
        ctx = runtime.run(args.video, start_ms=args.start_ms)

    async with ctx as stream:
        async for _ in stream:
            pass


if __name__ == "__main__":
    asyncio.run(main())
