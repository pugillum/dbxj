import time

import pytest

from dbxj.body import RECENT_RUNS, Body, format_duration, format_start_time, render_recent_runs
from dbxj.jobs import RunResult


@pytest.mark.parametrize(
    "ms, expected",
    [
        (None, "-"),
        (0, "0s"),
        (999, "0s"),
        (45_000, "45s"),
        (60_000, "1m 00s"),
        ((12 * 60 + 34) * 1000, "12m 34s"),
        ((2 * 3600 + 5 * 60 + 10) * 1000, "2h 05m 10s"),
        ((86400 + 3 * 3600 + 12 * 60 + 59) * 1000, "1d 03h 12m"),
    ],
)
def test_format_duration(ms, expected):
    assert format_duration(ms) == expected


@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.parametrize("ms", [None, 0])
def test_format_start_time_missing(ms):
    assert format_start_time(ms) == "-"


def test_format_start_time(utc):
    assert format_start_time(1_700_000_000_123) == "2023-11-14 22:13:20"


def test_render_recent_runs_failed_fetch():
    text = render_recent_runs(None)
    assert text.plain == "?"
    assert text.style == "red"


def test_render_recent_runs_pads_to_width():
    assert render_recent_runs([]).plain == " ".join(["-"] * RECENT_RUNS)
    assert render_recent_runs([RunResult.SUCCESS, RunResult.FAILED]).plain == "- - - ✓ ✗"


def test_render_recent_runs_all_symbols():
    results = [
        RunResult.SUCCESS,
        RunResult.FAILED,
        RunResult.RUNNING,
        RunResult.CANCELLED,
        RunResult.SUCCESS,
    ]
    text = render_recent_runs(results)
    assert text.plain == "✓ ✗ ● ⊘ ✓"
    assert [str(span.style) for span in text.spans] == [
        "green",
        "red",
        "yellow",
        "grey50",
        "green",
    ]


@pytest.mark.parametrize(
    "host, workspace_id, run_id, expected",
    [
        ("https://h.cloud.databricks.com", None, None, "https://h.cloud.databricks.com/jobs/1"),
        ("https://h.cloud.databricks.com/", None, None, "https://h.cloud.databricks.com/jobs/1"),
        ("https://h.com", 42, None, "https://h.com/jobs/1?o=42"),
        ("https://h.com", 42, 7, "https://h.com/jobs/1/runs/7?o=42"),
        ("https://h.com", None, 7, "https://h.com/jobs/1/runs/7"),
    ],
)
def test_job_url(host, workspace_id, run_id, expected):
    body = Body()
    body.ws_client = type("Client", (), {"config": type("Config", (), {"host": host})})()
    body.workspace_id = workspace_id
    assert body.job_url(1, run_id) == expected
