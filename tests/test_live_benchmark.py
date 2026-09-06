"""Pure live-benchmark classification helpers."""

import pytest

from benchmarks.live_cloud import (
    ARTIFACT_KIND,
    _compatible_artifact,
    _failure_class,
    _success_delta_ci,
    run_one,
)


def test_quota_failure_is_terminal_and_classified() -> None:
    assert _failure_class(1, "RateLimitError insufficient_quota", "error") == "quota"


def test_transient_provider_failure_is_distinguished_from_model_failure() -> None:
    assert _failure_class(1, "APIConnectionError", "error") == "transient_provider"
    assert _failure_class(1, "ProviderError: invalid request", "error") == "provider"


def test_success_has_no_failure_class() -> None:
    assert _failure_class(0, "", "success") is None


def test_paired_success_ci_is_deterministic() -> None:
    pairs = [
        {False: {"success": False}, True: {"success": True}},
        {False: {"success": False}, True: {"success": True}},
    ]
    assert _success_delta_ci(pairs) == (1.0, 1.0)


def test_resume_rejects_legacy_or_mismatched_artifacts() -> None:
    config = {
        "provider": "deepseek",
        "models": ["deepseek-v4-pro"],
        "scenarios": ["hello-world"],
        "seeds": [0],
        "repeats": 1,
        "full_task_budget": False,
    }
    assert not _compatible_artifact({"kind": "quackd-live-openai", "rows": []}, config)
    assert not _compatible_artifact({"kind": "quackd-live-v2", "rows": [], "config": {}}, config)
    assert _compatible_artifact({"kind": ARTIFACT_KIND, "rows": [], "config": config}, config)


def test_live_runner_rejects_unknown_memory_mode_before_any_call() -> None:
    with pytest.raises(ValueError, match="unknown memory mode"):
        run_one(
            "model",
            "deepseek",
            "fetch",
            0,
            False,
            0,
            0,
            1,
            True,
            memory_mode="unknown",
        )
