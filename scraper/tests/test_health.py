"""venue_status — the health status/precedence rules that drive the dashboard's
calm-vs-loud signal. The key invariant: an expected_empty (known-broken) venue
never shows as a loud error, however its empty page confuses the LLM."""
import run_scraper as rs


def _outcome(events=None, error=None, errored=False):
    report = {}
    if error:
        report["error"] = error
    return {"events": events, "report": report, "errored": errored}


def test_expected_empty_swallows_parse_error():
    cfg = {"expected_empty": True}
    status, _ = rs.venue_status(cfg, _outcome(events=[], error="Pass 1 JSON parse failed"), 0, 0)
    assert status == "idle"


def test_expected_empty_empty_is_idle():
    cfg = {"expected_empty": True}
    status, _ = rs.venue_status(cfg, _outcome(events=[]), 0, 0)
    assert status == "idle"


def test_real_error_is_loud():
    status, _ = rs.venue_status({}, _outcome(error="boom", errored=True), 0, 5)
    assert status == "error"


def test_zero_yield_with_history_is_error():
    # Not expected_empty, previously had events -> broke.
    status, _ = rs.venue_status({}, _outcome(events=[]), 0, 12)
    assert status == "error"


def test_zero_yield_never_had_is_warning():
    status, _ = rs.venue_status({}, _outcome(events=[]), 0, 0)
    assert status == "warning"


def test_cache_hit_is_ok():
    status, note = rs.venue_status({}, _outcome(events=None), 10, 10)
    assert status == "ok" and "cache" in note


def test_truncated_is_warning():
    o = _outcome(events=[{"t": 1}])
    o["report"]["truncated"] = True
    status, _ = rs.venue_status({}, o, 1, 1)
    assert status == "warning"


def test_healthy_is_ok():
    status, _ = rs.venue_status({}, _outcome(events=[{"t": 1}, {"t": 2}]), 2, 2)
    assert status == "ok"
