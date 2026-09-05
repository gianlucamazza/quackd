"""Opt-in benchmark geometry and trajectories, driven only by simulator time."""

import math

from quackd.sim2d.world import Ball, Person, World


def configure_targeted(world: World) -> None:
    if len(world.ducks) != 1 or world.heads or world.t != 0:
        raise ValueError("targeted-v1 needs a fresh single-duck world")
    # Four rigid rotations preserve feasibility without drawing from the physics RNG.
    angle = (world.seed % 4) * math.pi / 2

    def rotate(x: float, y: float) -> tuple[float, float]:
        return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)

    duck = world.ducks[0]
    duck.x, duck.y = rotate(-0.6, 0)
    duck.theta = angle
    bx, by = rotate(0.4, 0)
    world.ball = Ball(bx, by, start_x=bx, start_y=by)
    px, py = rotate(0.35, -0.45)
    world.people = [Person(px, py)]
    world.profile = "targeted-v1"
    world.profile_angle = angle


def advance_targeted(world: World, time_s: float) -> None:
    # Each half-cycle moves 0.9 m at 0.04 m/s, then pauses for ten seconds.
    phase = time_s % 65
    y = -0.45 + 0.04 * min(phase, 22.5) if phase < 32.5 else 0.45 - 0.04 * min(phase - 32.5, 22.5)
    a = world.profile_angle
    world.people[0].x = 0.35 * math.cos(a) - y * math.sin(a)
    world.people[0].y = 0.35 * math.sin(a) + y * math.cos(a)
