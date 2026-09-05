from benchmarks.paired_statistics import verified_comparison


def row(seed, repeat, context, success):
    return {
        "model": "test",
        "scenario": "fetch",
        "seed": seed,
        "repeat": repeat,
        "affective_context": context,
        "verified_success": success,
    }


def test_repeats_do_not_create_independent_seed_clusters():
    rows = [row(s, r, c, c) for s in range(2) for r in range(3) for c in (False, True)]
    result = verified_comparison(rows)
    assert result["seed_clusters"] == 2
    assert result["delta"] == 1
    assert result["degenerate"]
    assert not result["promotion_eligible"]


def test_unknown_does_not_become_a_verified_failure():
    result = verified_comparison([row(0, 0, False, None), row(0, 0, True, True)])
    assert result["delta"] is None
    assert result["unknown_pairs"] == 1
