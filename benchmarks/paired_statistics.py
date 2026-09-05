"""Verified-outcome estimates with seed-level resampling."""

import random
from collections import defaultdict
from statistics import mean


def verified_comparison(rows: list[dict]) -> dict:
    pairs = defaultdict(dict)
    for row in rows:
        key = (row["model"], row["scenario"], row["seed"], row["repeat"])
        pairs[key][row["affective_context"]] = row.get("verified_success")
    clusters = defaultdict(list)
    unknown = 0
    for key, pair in pairs.items():
        if set(pair) != {False, True} or any(v is None for v in pair.values()):
            unknown += 1
            continue
        clusters[key[2]].append(int(pair[True]) - int(pair[False]))
    if not clusters:
        return {"delta": None, "ci95": None, "unknown_pairs": unknown, "seed_clusters": 0}
    values = list(clusters.values())
    rng = random.Random(0)
    samples = sorted(
        mean(v for cluster in rng.choices(values, k=len(values)) for v in cluster)
        for _ in range(10000)
    )
    interval = [samples[250], samples[9749]] if len(values) >= 2 else None
    return {
        "delta": mean(v for cluster in values for v in cluster),
        "ci95": interval,
        "unknown_pairs": unknown,
        "seed_clusters": len(values),
        "method": "paired seed-cluster bootstrap, 10000 resamples, seed 0",
        "degenerate": interval is not None and interval[0] == interval[1],
        "promotion_eligible": bool(
            interval and interval[0] > 0 and not unknown and interval[0] != interval[1]
        ),
    }
