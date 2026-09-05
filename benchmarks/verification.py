"""Independent checks over retained simulator observations; missing evidence is unknown."""

import math


def verify(scenario: str, summary: dict, events: list[dict]) -> dict:
    states = [
        event.get("features", {}).get("state", {})
        for event in events
        if event.get("kind") == "observation"
    ]
    final = summary.get("final_state", {})
    if summary.get("transport") != "sim2d" or not states or not final:
        return {"success": None, "reason": "missing simulator evidence"}
    if scenario == "find-and-kick":
        moved = final.get("extras", {}).get("ball_displacement_m")
        return {
            "success": moved >= 0.3 if isinstance(moved, (float, int)) else None,
            "reason": "ball displacement must be at least 0.3 m",
        }
    if scenario == "fetch":
        if any("holding" not in state for state in states) or "holding" not in final:
            return {"success": None, "reason": "missing grasp telemetry"}
        held = next((state for state in states if state.get("holding") is True), None)
        if held is None:
            return {"success": False, "reason": "no observed successful grasp"}
        initial = states[0]
        if not all(
            isinstance(s.get(k), (float, int)) for s in (initial, held, final) for k in ("x", "y")
        ):
            return {"success": None, "reason": "missing pose evidence"}
        before = math.hypot(held["x"] - initial["x"], held["y"] - initial["y"])
        after = math.hypot(final["x"] - initial["x"], final["y"] - initial["y"])
        return {
            "success": final.get("holding") is True and before - after >= 0.5,
            "reason": "holding ball and reducing distance to start by at least 0.5 m",
            "return_progress_m": before - after,
        }
    if scenario in {"follow-me", "patrol-and-quack"}:
        previous = None
        pending = None
        legs = 0
        missing_scans = 0
        worst_missing = 0
        encounter = False
        quacks_due = 0
        missed_announcements = False
        for event in events:
            if event.get("kind") == "observation":
                state = event.get("features", {}).get("state", {})
                if pending and previous:
                    if not all(
                        isinstance(s.get(k), (int, float))
                        for s in (state, previous)
                        for k in ("x", "y")
                    ):
                        return {"success": None, "reason": "missing leg poses"}
                    distance = math.hypot(state["x"] - previous["x"], state["y"] - previous["y"])
                    target_visible = any(
                        d.get("label") == "person"
                        for d in event.get("features", {}).get("detections", [])
                    )
                    legs += distance > 0.01 and (scenario == "patrol-and-quack" or target_visible)
                pending = None
                previous = state
                seen = any(
                    d.get("label") in {"person", "pet"}
                    for d in event.get("features", {}).get("detections", [])
                )
                if scenario == "patrol-and-quack":
                    if seen and not encounter:
                        missed_announcements |= quacks_due > 0
                        quacks_due = 2
                    encounter = seen
                elif any(
                    d.get("label") == "person"
                    for d in event.get("features", {}).get("detections", [])
                ):
                    missing_scans = 0
            if event.get("kind") != "verb":
                continue
            name = event.get("name")
            if name == "quack" and event.get("ok"):
                quacks_due = max(0, quacks_due - 1)
            if name == "search_scan" and event.get("params", {}).get("target") == "person":
                missing_scans = 0 if event.get("ok") else missing_scans + 1
                worst_missing = max(worst_missing, missing_scans)
            if event.get("ok") and (
                (
                    scenario == "follow-me"
                    and name == "walk_to"
                    and event.get("params", {}).get("target") == "person"
                )
                or (scenario == "patrol-and-quack" and name == "walk")
            ):
                pending = event
        return {
            "success": legs >= 3
            and worst_missing <= 2
            and not missed_announcements
            and quacks_due == 0,
            "reason": "three moving legs, bounded lost scans, completed announcements",
            "moving_legs": legs,
            "max_lost_scans": worst_missing,
        }
    return {"success": None, "reason": "scenario verifier not implemented"}
