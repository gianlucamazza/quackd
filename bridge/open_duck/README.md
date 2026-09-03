# The quackd bridge for the Open Duck Mini v2

This directory is the only part of quackd that runs on a robot. It is not a Python package,
it is never imported by quackd, and it needs nothing but the standard library and numpy,
which your duck's Pi already has.

## Why it exists

The Open Duck Mini v2's runtime has no network control API. Its command source is a local
pygame gamepad and its only socket checks the IMU. So driving it from a laptop needs
something on the robot that turns a socket into that gamepad's seven floats.

## What it does, and does not, do

It does not reimplement the control loop. It **is** upstream's loop: it rebinds the class
upstream imports to read a gamepad, then runs upstream's own script. Three things follow.

- **The Feetech serial bus keeps exactly one owner**, because there is still exactly one
  process. Do not run this and `v2_rl_walk_mujoco.py` at the same time.
- **Nothing upstream is copied.** `Open_Duck_Mini_Runtime` carries no licence file, so it
  is yours to install and not ours to ship. The bridge imports what you installed.
- **Going limp is unreachable.** The only channel from the network to the body is seven
  floats and a few buttons. There is no method to refuse, because there is no method.

## Safety, in the order it matters

- **The deadman is evaluated by the control loop, not by a timer.** If no command arrives
  for 300 ms the three velocities go to zero, and that check runs inside the call upstream
  makes every tick. A server thread that is starved, wedged or dead still stops the duck.
- **The head holds instead of zeroing.** A velocity dropping to zero is what releasing a
  stick does, and the policy has seen it. A neck snapping to centre is not.
- **Head control is off unless you ask for it**, and then it is clamped inside upstream's
  own range and rate limited, because upstream warns that head control can break the head.
- **`stop` is a zero twist with torque still on.** Stop is not limp.
- **A fallen duck latches.** This robot has no get-up policy, so the bridge reports the fall
  and quackd's verbs refuse until a human stands it up. There is nothing to attempt.
- **The only e-stop is the power switch.** Keep a hand near it.
- **It binds loopback by default** and wants a token. This port walks a robot. Prefer
  `ssh -L 9871:127.0.0.1:9871 your-pi` over exposing it to a network.

## Install

Read [`install.sh`](install.sh), then run it on the Pi. It checks rather than fixes, and
every refusal is something to understand first. Full walkthrough:
[`docs/adapters/open_duck.md`](../../docs/adapters/open_duck.md).

## Try it with no robot at all

```bash
python quackd_duck_bridge.py check                       # what this duck would advertise
python quackd_duck_bridge.py serve --fake --seconds 60   # a synthetic 50 Hz loop
```

Then from a laptop, against that fake:

```bash
quackd doctor --robot open_duck:bridge --address tcp://127.0.0.1:9871
quackd run open-duck-lookout --robot open_duck:bridge --address tcp://127.0.0.1:9871
```

## Status

Never run on a physical duck by us. The protocol is exercised end to end in quackd's test
suite, against this daemon, over loopback. That makes "the protocol works" a fact and keeps
"the duck walked" a claim nobody has earned yet. If you run it on yours, please open an
issue: [`docs/open-duck-hardware-checklist.md`](../../docs/open-duck-hardware-checklist.md)
says what to send.
