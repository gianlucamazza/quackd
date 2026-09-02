"""The stationary head: a fixed camera in the cartoon world that changes nothing for ducks."""

from __future__ import annotations

import math

import pytest

from quackd.perception.color_blob import ColorBlobDetector
from quackd.sim2d.render import render_duckcam, render_headcam, render_topdown
from quackd.sim2d.world import DT, HEAD_POSES, HEAD_R, MAX_HEADS, World


def _run(world: World, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        world.step()


def test_a_head_draws_nothing_from_the_rng() -> None:
    # duck 0 and the ball are drawn before any head-aware clearance check, so they are
    # identical with and without a head (the person may move: a head is an obstacle)
    for seed in range(10):
        plain, with_head = World(seed=seed), World(seed=seed, n_heads=1)
        assert (plain.duck.x, plain.duck.y, plain.duck.theta) == (
            with_head.duck.x,
            with_head.duck.y,
            with_head.duck.theta,
        )
        assert (plain.ball.x, plain.ball.y) == (with_head.ball.x, with_head.ball.y)
        assert with_head.heads[0].x == HEAD_POSES[0][0]
        assert with_head.heads[0].y == HEAD_POSES[0][1]


def test_head_only_worlds_and_limits() -> None:
    w = World(seed=3, n_ducks=0, n_heads=1)
    assert w.ducks == [] and len(w.heads) == 1
    dist, _ = w.relative_head(w.ball.x, w.ball.y)
    assert dist >= 0.5  # the ball clears the head the way it clears duck 0
    with pytest.raises(ValueError, match="n_ducks"):
        World(seed=0, n_ducks=0)
    with pytest.raises(ValueError, match="n_heads"):
        World(seed=0, n_heads=MAX_HEADS + 1)
    assert len(World(seed=0, n_heads=MAX_HEADS).heads) == MAX_HEADS


@pytest.mark.parametrize("seed", range(10))
def test_the_shipped_pose_sees_the_ball_once_it_looks(seed: int) -> None:
    # the first HEAD_POSES entry was chosen for this: after a gaze toward the ball, the head
    # sees it on every seed 0-9 (at spawn, looking straight ahead, a ball at the edge of the
    # 90 deg field of view or behind duck 0 can be missed; search_scan turns the head)
    w = World(seed=seed, n_heads=1)
    _dist, bearing = w.relative_head(w.ball.x, w.ball.y)
    w.head_look(math.cos(bearing), math.sin(bearing))
    dets = ColorBlobDetector().detect(render_headcam(w))
    balls = [d for d in dets if d.label == "ball"]
    assert len(balls) == 1, f"seed {seed}: {[d.label for d in dets]}"
    true_dist, true_bearing = w.relative_head(w.ball.x, w.ball.y)
    assert balls[0].bearing_deg is not None
    assert abs(balls[0].bearing_deg - math.degrees(true_bearing)) < 5.0
    assert balls[0].est_distance_m is not None
    assert abs(balls[0].est_distance_m - true_dist) / true_dist < 0.3


def test_most_seeds_see_the_ball_before_looking() -> None:
    seen = 0
    for seed in range(10):
        dets = ColorBlobDetector().detect(render_headcam(World(seed=seed, n_heads=1)))
        seen += any(d.label == "ball" for d in dets)
    assert seen >= 8  # seed 5 hides the ball behind duck 0: a fixed camera's known limit


def test_head_look_turns_the_camera_and_reports_clamping() -> None:
    w = World(seed=1, n_ducks=0, n_heads=1, person=False)
    head = w.heads[0]
    # look 120 deg left: within a Reachy's range, well beyond a duck's 60 deg neck
    assert not w.head_look(math.cos(math.radians(120)), math.sin(math.radians(120)))
    assert abs(math.degrees(head.head_yaw) - 120.0) < 1e-6
    # the ball, placed where the camera now points, is dead ahead in the head cam
    ang = head.theta + head.head_yaw
    w.ball.x, w.ball.y = head.x + 0.6 * math.cos(ang), head.y + 0.6 * math.sin(ang)
    dets = ColorBlobDetector().detect(render_headcam(w))
    assert [d.label for d in dets] == ["ball"]
    assert dets[0].bearing_deg is not None and abs(dets[0].bearing_deg) < 3.0
    # pitch is clamped to 40 deg and reported
    assert w.head_look(1.0, 0.0, 5.0)
    assert abs(math.degrees(head.head_pitch) - 40.0) < 1e-6


def test_a_head_is_invisible_to_the_colour_detector() -> None:
    w = World(seed=0, n_heads=1, person=False)
    w.ball.present = False
    w.duck.x, w.duck.y = w.heads[0].x, w.heads[0].y + 0.4
    w.duck.theta = -math.pi / 2  # facing the head, 0.4 m away
    img = render_duckcam(w)
    assert img.getpixel((128, 100)) == (150, 150, 155)  # it is drawn...
    assert ColorBlobDetector().detect(img) == []  # ...and forges nothing


def test_ducks_stop_at_the_head_and_the_ball_bounces_off_it() -> None:
    w = World(seed=0, n_heads=1, person=False)
    head = w.heads[0]
    w.duck.x, w.duck.y, w.duck.theta = head.x, head.y + 0.5, -math.pi / 2
    w.ball.present = False
    for _ in range(40):
        w.set_velocity(0.3, 0.0, 0.0)
        w.step()
    assert math.hypot(w.duck.x - head.x, w.duck.y - head.y) >= w.duck.r + HEAD_R - 1e-6
    assert head.x == HEAD_POSES[0][0] and head.y == HEAD_POSES[0][1]  # bolted down
    w.ball.present = True
    w.ball.x, w.ball.y = head.x, head.y + 0.3
    w.ball.vx, w.ball.vy = 0.0, -1.0
    _run(w, 1.0)
    assert w.ball.y > head.y + HEAD_R  # never inside the head


def test_expressions_speech_and_snapshots() -> None:
    w = World(seed=2, n_heads=1)
    assert w.express("cheerful1") == 1.5 and w.heads[0].busy_until == 1.5
    w.head_say("hello there", "welcoming1")
    snap = w.head_snapshot()
    assert snap["busy"] and snap["expressions_played"] == 1 and snap["speech"] == 1
    assert "kicks" not in snap and "last_kick_ball_moved_m" not in snap
    assert w.snapshot()["heads"][0]["busy"]
    w.head_stop()
    assert not w.head_snapshot()["busy"]
    _run(w, 2.0)
    assert "heads" in w.snapshot() and "heads" not in World(seed=2).snapshot()


def test_renders_with_a_head_have_the_right_shape() -> None:
    w = World(seed=0, n_ducks=2, n_heads=2)
    assert render_topdown(w).size == (256, 256)
    assert render_headcam(w, 128, head_index=1).size == (128, 128)
    assert render_duckcam(w, 64, duck_index=1).size == (64, 64)
