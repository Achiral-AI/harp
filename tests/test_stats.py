"""StatsRegistry coverage."""

from __future__ import annotations

from harp.stats import StatsRegistry


def test_zero_state_snapshot() -> None:
    s = StatsRegistry().snapshot()
    assert s.total == 0
    assert s.served_local == 0
    assert s.local_serve_ratio == 0.0
    assert s.ineligibility_reasons == {}
    assert s.forward_reasons == {}


def test_serve_local_bumps_total_and_ratio() -> None:
    r = StatsRegistry()
    r.record_served_local()
    r.record_served_local()
    r.record_forwarded_upstream(reason="mode=proxy")
    s = r.snapshot()
    assert s.total == 3
    assert s.served_local == 2
    assert s.forwarded_upstream == 1
    assert abs(s.local_serve_ratio - (2 / 3)) < 1e-9
    assert s.forward_reasons == {"mode=proxy": 1}


def test_ineligibility_reasons_aggregate() -> None:
    r = StatsRegistry()
    r.record_ineligibility(reason="prior task history")
    r.record_ineligibility(reason="prior task history")
    r.record_ineligibility(reason="sub-input=tool_call_result")
    s = r.snapshot()
    assert s.ineligibility_reasons == {
        "prior task history": 2,
        "sub-input=tool_call_result": 1,
    }
    # record_ineligibility doesn't bump total on its own.
    assert s.total == 0


def test_local_only_rejection_path() -> None:
    r = StatsRegistry()
    r.record_rejected_local_only(reason="prior task history")
    s = r.snapshot()
    assert s.total == 1
    assert s.rejected_local_only == 1
    assert s.served_local == 0
    assert s.forwarded_upstream == 0
    assert s.ineligibility_reasons == {"prior task history": 1}


def test_local_error_path_counts_total_and_errors() -> None:
    r = StatsRegistry()
    r.record_local_error(reason="unsupported local request")
    s = r.snapshot()
    assert s.total == 1
    assert s.errors == 1
    assert s.served_local == 0
    assert s.forwarded_upstream == 0
    assert s.ineligibility_reasons == {"unsupported local request": 1}
