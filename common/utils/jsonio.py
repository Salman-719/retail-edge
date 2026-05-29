"""Atomic JSON read/write -- write to a temp file then rename, preventing
partial reads. (Ported from the current IEP2 storage helper.)"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
