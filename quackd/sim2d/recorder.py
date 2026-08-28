"""Turns a run into a shareable GIF: world view | duck-cam, with a caption strip.

The recorder hangs off the simulator's tick hook so motion between LLM turns is visible,
not just the snapshots the LLM saw. The GIF is the demo; the transcript is the proof.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from quackd.sim2d.render import render_duckcam, render_topdown

CAPTION_H = 22
MAX_FRAMES = 400


class FrameRecorder:
    def __init__(
        self, transport: Any, *, size: int = 256, every_s: float = 0.25, fps: int = 8
    ) -> None:
        self.world = getattr(transport, "world", None)
        self.size = size
        self.every_s = every_s
        self.fps = fps
        self.caption = "start"
        self.frames: list[Image.Image] = []
        self._last_t = -1e9
        hook = getattr(transport, "add_tick_hook", None)
        if hook is not None and self.world is not None:
            hook(self._on_tick)

    # the loop calls this with each frame it captured; we only keep the caption
    def capture(self, _img: Image.Image, caption: str) -> None:
        self.caption = caption[:60]
        if self.world is not None:
            self._append()

    def _on_tick(self, world: Any) -> None:
        if world.t - self._last_t >= self.every_s:
            self._append()

    def _append(self) -> None:
        if self.world is None:
            return
        self._last_t = self.world.t
        top = render_topdown(self.world, self.size)
        cam = render_duckcam(self.world, self.size)
        frame = Image.new("RGB", (self.size * 2 + 4, self.size + CAPTION_H), (30, 30, 30))
        frame.paste(top, (0, CAPTION_H))
        frame.paste(cam, (self.size + 4, CAPTION_H))
        draw = ImageDraw.Draw(frame)
        draw.text((6, 5), f"t={self.world.t:5.1f}s  {self.caption}", fill=(240, 240, 240))
        draw.text((self.size + 10, 5), "duck-cam", fill=(180, 180, 180))
        self.frames.append(frame)

    def save_gif(self, path: Path) -> Path:
        frames = self.frames
        if not frames and self.world is not None:
            self._append()
            frames = self.frames
        if len(frames) > MAX_FRAMES:
            stride = len(frames) / MAX_FRAMES
            frames = [frames[int(i * stride)] for i in range(MAX_FRAMES)]
        path.parent.mkdir(parents=True, exist_ok=True)
        palette = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT) for f in frames]
        hold = [1000 // self.fps] * len(palette)
        if hold:
            hold[-1] = 1500  # linger on the ending
        palette[0].save(
            path,
            save_all=True,
            append_images=palette[1:],
            duration=hold,
            loop=0,
            optimize=False,
        )
        return path
