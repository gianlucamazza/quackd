from benchmarks.verification import verify


def observation(x, holding=False, detections=None):
    return {
        "kind": "observation",
        "features": {
            "state": {"x": x, "y": 0, "holding": holding},
            "detections": detections or [],
        },
    }


def test_fetch_rejects_false_claim_and_short_return():
    summary = {
        "transport": "sim2d",
        "outcome": "success",
        "final_state": {"x": 0.8, "y": 0, "holding": True},
    }
    assert verify("fetch", summary, [observation(0), observation(1, True)])["success"] is False
    summary["final_state"]["x"] = 0.4
    assert verify("fetch", summary, [observation(0), observation(1, True)])["success"] is True
    assert verify("fetch", summary, [observation(0), observation(1)])["success"] is False


def test_follow_requires_real_movement():
    summary = {"transport": "sim2d", "final_state": {"x": 0, "y": 0}}
    events = [observation(0)]
    for _ in range(3):
        events += [
            {"kind": "verb", "name": "walk_to", "ok": True, "params": {"target": "person"}},
            observation(0),
        ]
    assert verify("follow-me", summary, events)["success"] is False


def test_missing_evidence_is_unknown():
    assert verify("fetch", {}, [])["success"] is None
