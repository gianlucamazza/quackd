#!/usr/bin/env bash
# Install quackd's bridge and camera server on an Open Duck Mini v2's Raspberry Pi.
#
# It checks rather than fixes. Every step it refuses is a step you should understand before
# a 42 cm biped starts taking commands from your network.
#
#   curl -fsSL .../install.sh | bash        is NOT how to run this. Read it, then:
#   bash install.sh
set -euo pipefail

RUNTIME_DIR="${RUNTIME_DIR:-$HOME/Open_Duck_Mini_Runtime}"
VENV="${VENV:-$HOME/.virtualenvs/open-duck-mini-runtime}"
PORT_DEV="${PORT_DEV:-/dev/ttyACM0}"
TOKEN_FILE="${TOKEN_FILE:-/etc/quackd/duck-bridge.token}"
DUCK_CONFIG="${DUCK_CONFIG:-$HOME/duck_config.json}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n== %s\n' "$1"; }
warn() { printf 'warning: %s\n' "$1"; }
die() { printf '\nstopped: %s\n' "$1" >&2; exit 1; }

say "checking the robot's own runtime"
[ -d "$RUNTIME_DIR" ] || die "no runtime at $RUNTIME_DIR. Install it first, from
  https://github.com/apirrone/Open_Duck_Mini_Runtime (branch v2). quackd does not ship it."
[ -x "$VENV/bin/python" ] || die "no virtualenv at $VENV. Upstream's README uses
  mkvirtualenv -p python3 open-duck-mini-runtime, then pip install -e . in the checkout.
  Set VENV=... if yours lives elsewhere."
"$VENV/bin/python" -c 'import mini_bdx_runtime' \
  || die "$VENV cannot import mini_bdx_runtime. Run pip install -e . inside $RUNTIME_DIR."

say "checking that nothing else owns the serial bus"
[ -e "$PORT_DEV" ] || die "$PORT_DEV is missing. Is the servo board plugged in and powered?"
[ -r "$PORT_DEV" ] || die "$PORT_DEV is not readable by you. sudo usermod -aG dialout $USER, then log out and in."
if pgrep -f 'v2_rl_walk_mujoco.py' >/dev/null; then
  die "upstream's walk script is already running. The Feetech bus has exactly one owner,
  and this service replaces however you started that script before. Stop it first."
fi

say "checking I2C and the IMU"
[ -e /dev/i2c-1 ] || warn "no /dev/i2c-1. Enable it with sudo raspi-config nonint do_i2c 0, then reboot."
if command -v i2cdetect >/dev/null && [ -e /dev/i2c-1 ]; then
  i2cdetect -y 1 | grep -q ' 28 ' || warn "no BNO055 at 0x28 on i2c-1."
fi

say "checking Wi-Fi power save, which is the difference between 10 Hz and a stutter"
if command -v iw >/dev/null; then
  iw dev wlan0 get power_save 2>/dev/null | grep -q 'off' \
    || warn "Wi-Fi power save is on. sudo iw dev wlan0 set power_save off"
fi

say "checking who owns the camera"
if grep -q '"camera"[[:space:]]*:[[:space:]]*true' "$DUCK_CONFIG" 2>/dev/null; then
  warn "duck_config.json has expression_features.camera true, so the robot's own runtime
  owns the camera and quackd-duck-camd will refuse to start. Two processes cannot own one
  camera. Set that flag false to let quackd serve frames instead, or accept no frames and
  the verbs that need them will simply not exist."
fi

say "installing the bridge and the camera server to /opt/quackd"
sudo install -m 0755 -D "$HERE/quackd_duck_bridge.py" /opt/quackd/quackd_duck_bridge.py
sudo install -m 0755 -D "$HERE/quackd_duck_camd.py" /opt/quackd/quackd_duck_camd.py

say "generating a token"
if [ ! -f "$TOKEN_FILE" ]; then
  sudo install -d -m 0700 "$(dirname "$TOKEN_FILE")"
  openssl rand -hex 32 | sudo tee "$TOKEN_FILE" >/dev/null
  sudo chmod 600 "$TOKEN_FILE"
  printf 'wrote a new token to %s\n' "$TOKEN_FILE"
fi

say "installing the services"
sudo install -m 0644 -D "$HERE/quackd-duck-bridge.service" \
  /etc/systemd/system/quackd-duck-bridge.service
sudo install -m 0644 -D "$HERE/quackd-duck-camd.service" \
  /etc/systemd/system/quackd-duck-camd.service
sudo systemctl daemon-reload

cat <<'NEXT'

Installed, and deliberately not started.

Before you start anything:

  1. Edit /etc/systemd/system/quackd-duck-bridge.service so the interpreter, the script
     path and the walk policy path are yours. The policy is BEST_WALK_ONNX_2.onnx, from
     https://github.com/apirrone/Open_Duck_Mini (Apache-2.0). quackd does not ship it.
  2. Put your duck on a stand, with its feet off the ground.
  3. Dry run both, with no robot and no camera at all:
        python /opt/quackd/quackd_duck_camd.py --fake --seconds 30
        python /opt/quackd/quackd_duck_bridge.py serve --fake --seconds 30
  4. Start the camera first, so the bridge can advertise it. Add
        --camera-url http://<this-pi>:9872/snapshot.jpg
     to the bridge unit's ExecStart. Without it the bridge reports no camera, and observe,
     go_to, search_scan and approach_and will not exist rather than exist and fail.
        sudo systemctl start quackd-duck-camd
        curl -s http://127.0.0.1:9872/healthz
        sudo systemctl start quackd-duck-bridge
        journalctl -u quackd-duck-bridge -f
  5. From your laptop, safest first, over an ssh tunnel because the bridge binds loopback.
     Forward both ports, and tell quackd where the camera is on your side of the tunnel:
        ssh -L 9871:127.0.0.1:9871 -L 9872:127.0.0.1:9872 <your-pi>
        quackd doctor --robot open_duck:bridge --address tcp://127.0.0.1:9871
        quackd run open-duck-lookout --robot open_duck:bridge \
            --address tcp://127.0.0.1:9871 \
            --camera-url http://127.0.0.1:9872/snapshot.jpg

Nothing in open-duck-lookout's allowlist moves a leg. Run it before you ever run a task
that walks, and remember this robot cannot get back up if it falls.
NEXT
