"""The camera server that runs on the duck's Pi, exercised with no Pi and no camera.

The last test is the one that matters: it stands up the real camera server, tells the real
bridge daemon where it is, and has the real quackd client fetch a frame through the whole
chain. That is what turns `observe` from a promise into a picture.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest

from quackd.adapters.open_duck import OpenDuckAdapter
from quackd.adapters.open_duck.bridge import OpenDuckBridge

REPO = Path(__file__).resolve().parents[1]
CAMD = REPO / "bridge" / "open_duck" / "quackd_duck_camd.py"
DAEMON = REPO / "bridge" / "open_duck" / "quackd_duck_bridge.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def camd() -> ModuleType:
    return _load(CAMD, "quackd_duck_camd")


@pytest.fixture(scope="module")
def daemon() -> ModuleType:
    return _load(DAEMON, "quackd_duck_bridge")


def get(url: str, timeout: float = 3.0) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def wait_for_frame(store, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if store.get()[0] is not None:
            return
        time.sleep(0.02)
    raise AssertionError("no frame was captured in time")


# ── the store ───────────────────────────────────────────────────────────────────────────


def test_the_store_starts_empty_and_reports_it(camd: ModuleType) -> None:
    store = camd.FrameStore()
    assert store.get() == (None, 0.0)
    health = store.health(now=10.0)
    assert health["ok"] is False and health["age_s"] is None and health["frames"] == 0


def test_the_store_keeps_only_the_newest_frame(camd: ModuleType) -> None:
    store = camd.FrameStore()
    store.put(b"old", (8, 8), now=100.0)
    store.put(b"new", (8, 8), now=101.0)
    jpeg, at = store.get()
    assert jpeg == b"new" and at == 101.0
    assert store.health(now=101.5)["age_s"] == 0.5
    assert store.health(now=101.5)["frames"] == 2


def test_a_capture_failure_is_recorded_and_does_not_lose_the_last_frame(camd: ModuleType) -> None:
    store = camd.FrameStore()
    store.put(b"good", (8, 8), now=1.0)
    store.fail("the camera unplugged itself")
    assert store.get()[0] == b"good", "a hiccup must not blank the feed"
    health = store.health(now=2.0)
    assert health["errors"] == 1 and "unplugged" in health["last_error"]


# ── the http surface ────────────────────────────────────────────────────────────────────


def test_a_snapshot_before_the_first_capture_is_a_clean_503(camd: ModuleType) -> None:
    store = camd.FrameStore()
    server = camd.serve(store, "127.0.0.1", 0)
    try:
        port = server.server_address[1]
        code, body, ctype = get(f"http://127.0.0.1:{port}/snapshot.jpg")
        assert code == 503 and "json" in ctype
        assert json.loads(body)["reason"] == "no frame captured yet"
    finally:
        server.shutdown()


def test_it_serves_a_jpeg_and_a_health_page(camd: ModuleType) -> None:
    store = camd.FrameStore()
    stop = threading.Event()
    threading.Thread(
        target=camd.capture_loop, args=(store, camd.FakeCamera(64), 20.0, stop), daemon=True
    ).start()
    server = camd.serve(store, "127.0.0.1", 0)
    try:
        wait_for_frame(store)
        port = server.server_address[1]
        code, body, ctype = get(f"http://127.0.0.1:{port}/snapshot.jpg")
        assert code == 200 and ctype == "image/jpeg"
        assert body[:2] == b"\xff\xd8", "a real JPEG, not a description of one"

        code, body, _ = get(f"http://127.0.0.1:{port}/healthz")
        health = json.loads(body)
        assert code == 200 and health["ok"] is True
        assert health["frames"] >= 1 and health["bytes"] > 0 and health["age_s"] < 5

        assert get(f"http://127.0.0.1:{port}/anything-else")[0] == 404
    finally:
        stop.set()
        server.shutdown()


def test_nothing_in_this_server_can_move_the_robot(camd: ModuleType) -> None:
    """It reads a camera and answers GET. There is no control path to get wrong."""
    code = "\n".join(
        line for line in CAMD.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
    )
    for forbidden in ("do_POST", "do_PUT", "do_DELETE", "mini_bdx_runtime", "HWI(", "set_position"):
        assert forbidden not in code, f"camd should not contain {forbidden!r}"
    # and the only request verb it answers at all
    assert code.count("def do_") == 1 and "def do_GET" in code


# ── two processes cannot own one camera ─────────────────────────────────────────────────


def test_it_refuses_to_fight_the_runtime_for_the_camera(camd: ModuleType, tmp_path) -> None:
    config = tmp_path / "duck_config.json"
    config.write_text('{"expression_features": {"camera": true}}')
    assert camd.runtime_owns_the_camera(str(config)) is True
    assert camd.main(["--duck-config", str(config), "--seconds", "0.1"]) == 2

    config.write_text('{"expression_features": {"camera": false}}')
    assert camd.runtime_owns_the_camera(str(config)) is False
    assert camd.runtime_owns_the_camera(str(tmp_path / "absent.json")) is False


def test_fake_mode_runs_even_where_the_runtime_owns_the_camera(camd: ModuleType, tmp_path) -> None:
    config = tmp_path / "duck_config.json"
    config.write_text('{"expression_features": {"camera": true}}')
    assert (
        camd.main(["--duck-config", str(config), "--fake", "--port", "0", "--seconds", "0.2"]) == 0
    )


# ── the whole chain ─────────────────────────────────────────────────────────────────────


async def test_quackd_sees_through_the_camera_server(camd: ModuleType, daemon: ModuleType) -> None:
    """camd serves a frame, the bridge advertises where, and quackd fetches a real image.

    Without this the duck can walk and chirp but not see, and `observe`, `go_to`,
    `search_scan` and `approach_and` do not exist for it at all."""
    store = camd.FrameStore()
    stop = threading.Event()
    threading.Thread(
        target=camd.capture_loop, args=(store, camd.FakeCamera(96), 20.0, stop), daemon=True
    ).start()
    cam_server = camd.serve(store, "127.0.0.1", 0)
    cam_port = cam_server.server_address[1]
    wait_for_frame(store)

    core = daemon.BridgeCore(
        capabilities={"camera": True, "speaker": True, "antennas": False, "microphone": False},
        camera_url=f"http://127.0.0.1:{cam_port}/snapshot.jpg",
    )
    bridge_server = daemon.Server(core, "127.0.0.1", 0)
    bridge_server.start()
    try:
        adapter = OpenDuckAdapter(OpenDuckBridge(f"tcp://127.0.0.1:{bridge_server.port}"))
        manifest = await adapter.connect()
        # the camera is what brings these four verbs into existence
        assert {"observe", "go_to", "search_scan", "approach_and"} <= set(manifest.verb_names())
        frame = await adapter.get_frame()
        assert frame is not None and frame.size == (96, 96)
        assert frame.mode == "RGB"
        await adapter.disconnect()
    finally:
        stop.set()
        cam_server.shutdown()
        bridge_server.stop()
        bridge_server.join(timeout=2)


async def test_a_duck_with_no_camera_server_simply_has_no_camera_verbs(daemon: ModuleType) -> None:
    core = daemon.BridgeCore(capabilities={"camera": False, "speaker": True})
    server = daemon.Server(core, "127.0.0.1", 0)
    server.start()
    try:
        adapter = OpenDuckAdapter(OpenDuckBridge(f"tcp://127.0.0.1:{server.port}"))
        manifest = await adapter.connect()
        assert not {"observe", "go_to", "search_scan", "approach_and"} & set(manifest.verb_names())
        assert await adapter.get_frame() is None
        await adapter.disconnect()
    finally:
        server.stop()
        server.join(timeout=2)


async def test_a_narrowed_robot_refuses_the_run_instead_of_crashing(
    daemon: ModuleType, tmp_path
) -> None:
    """`validate` checks the STATIC manifest, which describes a fully built duck. A duck
    that reports no camera at connect has a narrower vocabulary, and the agent loop used to
    reach tool_schemas and raise a bare VerbNotFound with the robot already connected."""
    from quackd.agent.loop import AgentLoop, RunConfig
    from quackd.duckfile.parser import load_duck
    from quackd.transport.base import TransportError

    core = daemon.BridgeCore(capabilities={"camera": False, "speaker": True})
    server = daemon.Server(core, "127.0.0.1", 0)
    server.start()
    try:
        adapter = OpenDuckAdapter(OpenDuckBridge(f"tcp://127.0.0.1:{server.port}"))
        loop = AgentLoop(
            RunConfig(
                duck=load_duck("open-duck-scout"),  # needs search_scan, which needs a camera
                provider=None,  # never reached: we refuse before the first turn
                transport=adapter,
                runs_dir=tmp_path,
            )
        )
        with pytest.raises(TransportError) as caught:
            await loop.run()
        message = str(caught.value)
        # observe and go_to are what the task *requires* and a camera is what provides them
        assert "requires observe, go_to" in message and "does not provide" in message
        assert "narrower than its description" in message
        await adapter.disconnect()
    finally:
        server.stop()
        server.join(timeout=2)


async def test_a_verb_a_task_merely_allows_is_dropped_not_fatal(
    daemon: ModuleType, tmp_path
) -> None:
    """A v1 task may allow more than it needs. `open-duck-scout` allows gaze, but head
    control is off by default, and a duck with no head should still do the task."""
    from quackd.agent.loop import AgentLoop, RunConfig
    from quackd.agent.providers.fake import FakeProvider
    from quackd.duckfile.parser import load_duck

    core = daemon.BridgeCore(
        capabilities={"camera": True, "speaker": True, "antennas": False, "microphone": False},
        camera_url=None,
    )
    core.capabilities["camera"] = True  # a camera, but deliberately no head and no antennas
    server = daemon.Server(core, "127.0.0.1", 0)
    server.start()
    controller = daemon.NetworkController(core, 20)
    # a stand-in for upstream's loop, so the bridge reports a healthy control rate
    ticking = threading.Event()

    settled = threading.Event()

    def tick() -> None:
        while not ticking.is_set():
            controller.get_last_command()
            if core.loop_hz >= 40.0:
                settled.set()
            time.sleep(0.02)

    threading.Thread(target=tick, daemon=True).start()
    # the heartbeat refuses a starved loop, and under a loaded suite the first tick can
    # arrive after the first health poll, so wait for a real rate before connecting
    assert await asyncio.to_thread(settled.wait, 5.0), "the stand-in loop never got going"
    lines: list[str] = []
    try:
        adapter = OpenDuckAdapter(OpenDuckBridge(f"tcp://127.0.0.1:{server.port}"))
        loop = AgentLoop(
            RunConfig(
                duck=load_duck("open-duck-scout"),
                provider=FakeProvider.for_duck("open-duck-scout"),
                transport=adapter,
                runs_dir=tmp_path,
                log=lines.append,
            )
        )
        result = await loop.run()
        assert result.outcome in ("success", "failure", "budget"), result.reason
        assert any("does not have gaze" in line for line in lines), lines
    finally:
        ticking.set()
        server.stop()
        server.join(timeout=2)
