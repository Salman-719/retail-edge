from typing import Iterator, Tuple
import numpy as np

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable


@runtime_checkable
class FrameSource(Protocol):
    def frames(self) -> Iterator[Tuple[int, np.ndarray]]:
        ...

    def is_available(self) -> bool:
        ...

    def release(self) -> None:
        ...


if __name__ == "__main__":
    print("FrameSource protocol OK")
