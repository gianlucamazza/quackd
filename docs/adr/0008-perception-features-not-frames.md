# ADR-0008: Features, not frames — a colour-blob detector by default

**Status:** accepted · **Date:** 2026-08-28

## Context

Upstream's principle: put perception next to the sensor and publish *features* ("ball at
(x, y)", "person detected"), tens of bytes at 10–30 Hz. The steering loop needs detections
at ~10 Hz on a laptop; the LLM needs a sentence, not a pixel grid, to decide the next verb.

## Decision

- `Detector` protocol → `[Detection(label, cx, cy, area, confidence, bearing_deg,
  est_distance_m)]`. Verbs and prompts consume only this.
- Default `ColorBlobDetector` (OpenCV HSV threshold, ~1 ms/frame, zero downloads).
  The sim draws the ball in a known orange (H≈16 in OpenCV's 0–180 scale), the person in
  blue, a pet in green. Geometry: `bearing = -atan((cx - w/2) / f)` (positive = left,
  upstream's +yaw convention); `distance = f · r / radius_px` for round targets and
  `f · half_width / (w_px/2)` for upright ones, with `f = (w/2) / tan(FOV/2)`.
- `YoloDetector` (`quackd[yolo]`, lazy `ultralytics` import) maps COCO classes to the same
  labels for real cameras. Not needed for the demo.
- The LLM sees a summary line (`ball at bearing 12° left, ~0.80 m`) plus, for vision
  providers, the last frame or two as images; older images are dropped from history.

## Consequences

- Tuning for a real orange ball = one `HSVRange` (documented in `docs/faq.md`); a real
  IMX219 = `fov_deg=62`. Nothing else changes.
- Distance from apparent size is crude (±20 %) but monotonic, which is all `walk_to`
  needs; the stop condition is verified by the kick result or a fresh frame, not trusted.
- When upstream ships `mediad`'s feature stream, it becomes one more `Detector` that reads
  a socket instead of an image.
