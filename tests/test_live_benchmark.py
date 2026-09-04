"""Pure live-benchmark classification helpers."""

from benchmarks.live_cloud import _failure_class


def test_quota_failure_is_terminal_and_classified() -> None:
    assert _failure_class(1, "RateLimitError insufficient_quota", "error") == "quota"


def test_transient_provider_failure_is_distinguished_from_model_failure() -> None:
    assert _failure_class(1, "APIConnectionError", "error") == "transient_provider"
    assert _failure_class(1, "ProviderError: invalid request", "error") == "provider"


def test_success_has_no_failure_class() -> None:
    assert _failure_class(0, "", "success") is None
