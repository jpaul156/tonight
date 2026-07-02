"""clean_json — strips code fences and recovers a truncated LLM array. The
truncation recovery is what keeps a cut-off Pass 1 response from losing every
event instead of just the last partial one."""
import json

import scraper_core as sc


def test_plain_array_passes_through():
    raw = '[{"title": "A"}]'
    assert json.loads(sc.clean_json(raw)) == [{"title": "A"}]


def test_strips_json_fence():
    raw = '```json\n[{"title": "A"}]\n```'
    assert json.loads(sc.clean_json(raw)) == [{"title": "A"}]


def test_strips_bare_fence():
    raw = '```\n[{"title": "A"}]\n```'
    assert json.loads(sc.clean_json(raw)) == [{"title": "A"}]


def test_recovers_truncated_array():
    # Response cut off mid-third-object: recover the two complete ones.
    raw = '[{"title": "A"}, {"title": "B"}, {"title": "C'
    recovered = json.loads(sc.clean_json(raw))
    assert [e["title"] for e in recovered] == ["A", "B"]


def test_recovers_truncated_with_trailing_comma():
    raw = '[{"title": "A"}, {"title": "B"},'
    recovered = json.loads(sc.clean_json(raw))
    assert [e["title"] for e in recovered] == ["A", "B"]


def test_fenced_complete_is_not_flagged_truncated():
    # A fenced-but-complete response must NOT set the truncated flag — routine
    # fence stripping isn't data loss (this was a false-positive on the
    # dashboard where every LLM venue showed "truncated").
    report = {}
    sc.clean_json('```json\n[{"title": "A"}]\n```', report=report)
    assert "truncated" not in report


def test_real_truncation_sets_flag():
    report = {}
    sc.clean_json('[{"title": "A"}, {"title": "B"}, {"title": "C', report=report)
    assert report.get("truncated") is True
