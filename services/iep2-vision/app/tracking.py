from __future__ import annotations

import numpy as np


def as_float_bbox(values: np.ndarray) -> list[float]:
    return [float(v) for v in values.tolist()]
