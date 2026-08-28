"""An optional YOLO detector (`quackd[yolo]`) for real cameras and cluttered scenes.

Lazily imports `ultralytics` so the default install never pays for it. Maps COCO classes
onto the same labels the colour-blob detector emits — `ball`, `person`, `pet` — so verbs
and `.duck` files do not care which detector produced a detection.
"""

from __future__ import annotations

import math
from typing import Any

from PIL import Image

from quackd.perception.base import Detection

COCO_TO_LABEL = {"sports ball": "ball", "person": "person", "cat": "pet", "dog": "pet"}
HEIGHT_M = {"ball": 0.10, "person": 1.6, "pet": 0.35}


class YoloDetector:
    name = "yolo"

    def __init__(self, model: str = "yolov8n.pt", conf: float = 0.4, fov_deg: float = 62.0) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "YoloDetector needs ultralytics: uv pip install 'quackd[yolo]'"
            ) from e
        self._model: Any = YOLO(model)
        self.conf = conf
        self.fov_deg = fov_deg

    def detect(self, image: Image.Image) -> list[Detection]:
        w, h = image.size
        f = (w / 2) / math.tan(math.radians(self.fov_deg) / 2)
        results = self._model.predict(image, conf=self.conf, verbose=False)
        out: list[Detection] = []
        for res in results:
            names = res.names
            for box in res.boxes:
                label = COCO_TO_LABEL.get(names[int(box.cls)])
                if label is None:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                cx, bh = (x1 + x2) / 2, max(1.0, y2 - y1)
                out.append(
                    Detection(
                        label=label,
                        cx=cx / w,
                        cy=(y1 + y2) / 2 / h,
                        area=(x2 - x1) * bh / (w * h),
                        confidence=float(box.conf),
                        bearing_deg=round(-math.degrees(math.atan((cx - w / 2) / f)), 1),
                        est_distance_m=round(f * HEIGHT_M[label] / bh, 3),
                    )
                )
        return out
