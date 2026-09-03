# Open Duck Mini v2: the first hardware run

Nobody has run quackd against a physical Open Duck Mini v2. If you have one, this page is
the order to do it in. Every step has an abort condition, and they are ordered so that the
duck's feet do not touch the ground until step 8.

**Before anything else.** This robot has no get-up-after-fall policy. If it goes over, quackd
cannot recover it and every verb that moves it will refuse until you pick it up. Work with
the duck on a stand, keep a hand near the power switch, and do not skip the stand.

## 1. Upstream's own teleop works first

Drive the duck with its gamepad, the way its README says, with quackd nowhere in sight.

> Abort if it does not walk. Something in the build, the calibration or the offsets is
> wrong, and adding quackd will only make it harder to see.

## 2. Nothing else owns the serial bus

```bash
pgrep -af v2_rl_walk_mujoco.py
systemctl status quackd-duck-bridge
```

The Feetech bus has exactly one owner, and quackd's daemon **replaces** however you started
the walk script before.

> Abort if anything is still holding `/dev/ttyACM0`.

## 3. What the bridge thinks your duck is

```bash
python /opt/quackd/quackd_duck_bridge.py check
```

Read the `capabilities` block against what you actually soldered, and the `limits` block
against upstream's numbers. Then read the seven element command layout in
[`docs/adapters/open_duck.md`](adapters/open_duck.md) and satisfy yourself it matches what
upstream's teleop sends.

> Abort if the capabilities are wrong. They come from your `duck_config.json`, and they
> decide which verbs exist.

## 4. The protocol, with no robot at all

On the Pi, in one terminal:

```bash
python /opt/quackd/quackd_duck_bridge.py serve --fake --seconds 120
```

On your laptop, through an ssh tunnel because the bridge binds loopback:

```bash
ssh -L 9871:127.0.0.1:9871 your-pi
quackd doctor --robot open_duck:bridge --address tcp://127.0.0.1:9871
quackd list-verbs --robot open_duck:bridge
```

> Abort on a protocol mismatch. Update whichever side is older rather than working around it.

## 5. Measure the link before you trust it

```bash
ping -c 100 your-pi
sudo iw dev wlan0 set power_save off      # on the Pi, if it was on
```

The deadman zeroes the duck after 300 ms of silence.

> Abort if p99 latency is above about 100 ms. Use Ethernet or a USB gadget link instead, or
> the duck will stutter and stop in the middle of steps.

## 6. Dry run, feet still off the ground

```bash
quackd run open-duck-lookout --robot open_duck:bridge --address tcp://127.0.0.1:9871 --dry-run
```

Verbs run, nothing moves.

## 7. The head only, feet still off the ground

```bash
quackd run open-duck-lookout --robot open_duck:bridge --address tcp://127.0.0.1:9871
```

Nothing in this task's allowlist moves a leg. If you started the daemon without
`--enable-head`, `gaze` will not exist at all and the task will report what it can see
without moving, which is a perfectly good first result.

> Abort on any servo whine, buzzing or stall. Head control is upstream-flagged as
> experimental and it can break the head.

## 8. Walk in place, feet still off the ground

Watch `loop_hz` in `quackd doctor` while it runs. Anything below 35 Hz fails the heartbeat
on purpose, because a starved Pi walks badly with no other symptom.

## 9. Test the deadman before you need it

With the duck walking in place on the stand, pull your laptop's Wi-Fi.

> The duck must stop within about a third of a second. **An untested deadman is not a
> deadman.** Do not go to step 10 until you have seen this work.

## 10. Feet down

Clear floor, hand on the power switch:

```bash
quackd run open-duck-scout --robot open_duck:bridge --address tcp://127.0.0.1:9871 --max-steps 10
```

## What to send

Open an issue with the Open Duck hardware report template, and attach:

1. `quackd doctor --robot open_duck:bridge --address ...`, in full.
2. `python /opt/quackd/quackd_duck_bridge.py check`, in full. It carries your capabilities
   and limits, which is how we know what was actually tested.
3. `git rev-parse HEAD` inside your `Open_Duck_Mini_Runtime` checkout, and which walk policy
   you used.
4. `journalctl -u quackd-duck-bridge` for the run.
5. The first 40 lines of `transcript.jsonl`.
6. Which step you reached, what the duck physically did, and **whether you tested the
   deadman in step 9**.
7. A video or a GIF, if you can.

A report earns a row on this adapter's page and our thanks. Only a run on the maintainer's
own duck flips a status to ✅, which is the same rule every other adapter lives under.
