"""Shared fixtures for IEP2 unit tests.

Adds the IEP2 package root to sys.path so `detector.detector`, `reid.reid`, and
`metrics` import without pip install (mirrors test_gallery.py). Provides bare
YOLO/ReID clients whose ZMQ sockets are stubbed, so the inference-deadline tests
exercise the real detect()/extract() logic with no transport and no GPU.
"""
import os
import sys

import pytest

# Make the IEP2 package importable without pip install.
_IEP2_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "services", "iep2_vision")
)
if _IEP2_ROOT not in sys.path:
    sys.path.insert(0, _IEP2_ROOT)


class _AsyncNoopSocket:
    """Stand-in for the ZMQ PUSH socket: send() is an async no-op."""

    def __init__(self):
        self.sent = []

    async def send(self, payload, *args, **kwargs):
        self.sent.append(payload)
        return None


@pytest.fixture
def yolo_client():
    """A YoloClient with stubbed sockets and no reader loop.

    Built via __new__ so __init__ never creates real ZMQ sockets. Tests resolve
    entries in _pending directly to simulate the yolo-service replying (or never
    replying, to exercise the deadline).
    """
    from detector.detector import YoloClient

    c = YoloClient.__new__(YoloClient)
    c._camera_id = "cam-test"
    c._pending = {}
    c._reader_task = None
    c._timeouts = 0
    c._push = _AsyncNoopSocket()
    return c


@pytest.fixture
def reid_client():
    """A ReidClient with stubbed sockets and no reader loop."""
    from reid.reid import ReidClient

    c = ReidClient.__new__(ReidClient)
    c._camera_id = "cam-test"
    c._pending = {}
    c._reader_task = None
    c._timeouts = 0
    c._push = _AsyncNoopSocket()
    return c
