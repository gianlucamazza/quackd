"""Features, not frames.

Mirroring upstream's principle, the LLM sees "ball at bearing 12° left, ~0.8 m", not pixels,
and the steering loop closes on detections at ~10 Hz without an LLM in the way. This package
turns images into that.
"""
