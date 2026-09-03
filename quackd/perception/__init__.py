"""Features, not frames.

Mirroring upstream's principle, the LLM sees "ball at bearing 12° left, ~0.8 m", not pixels,
and the steering loop closes on detections at ~10 Hz without an LLM in the way. This package
turns images into that.
"""

from __future__ import annotations

from collections.abc import Container
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quackd.perception.base import Detector

__all__ = ["detector_for"]


def detector_for(sensors: Container[str], current: Detector | None = None) -> Detector | None:
    """A robot with a camera needs something to look at its frames with. Any robot.

    Keying this on the backend being `sim2d` is the bug that made every hardware body run
    blind: it fetched a frame, detected nothing because nothing was detecting, and reported
    that it could not see. 0.5 fixed that in `quackd run` and missed `serve-mcp`, which is
    why the decision now lives in one function that both entry points call.

    Call it with what the robot said when it *connected*, not with its description. A
    rosbridge base has no camera in its static manifest and may well have one in its live
    one, and the description of a fully built duck promises a camera the duck in front of
    you may not have been built with.
    """
    if current is not None or "camera" not in sensors:
        return current
    from quackd.perception.color_blob import ColorBlobDetector

    return ColorBlobDetector()
