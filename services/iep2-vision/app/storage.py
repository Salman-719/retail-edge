from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = SERVICE_ROOT / "runtime"


def ensure_runtime_dir() -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR


def run_dir(run_id: str) -> Path:
    path = ensure_runtime_dir() / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_test1_dir(override: str | None = None) -> Path:
    candidates: list[Path] = []

    if override:
        candidates.append(Path(override).expanduser())

    env_dir = os.getenv("IEP2_TEST1_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    for base in [Path.cwd(), SERVICE_ROOT, *SERVICE_ROOT.parents]:
        candidates.append(base / "testing-data" / "Test1")
        candidates.append(base / "testing-data" / "test1")

    for candidate in candidates:
        resolved = candidate.resolve()
        if (
            resolved.exists()
            and (resolved / "Camera1.mp4").exists()
            and (resolved / "Camera2.mp4").exists()
        ):
            return resolved

    searched = ", ".join(str(c) for c in candidates[:8])
    raise FileNotFoundError(
        "Could not locate testing-data/Test1 with Camera1.mp4 and Camera2.mp4. "
        f"Set IEP2_TEST1_DIR or pass test1_dir. Searched: {searched}"
    )

