from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.jobs import (
    BaseJob,
    BaseRun,
    JobSettings,
    RunLifecycleStateV2State,
    RunStatus,
    TerminationCodeCode,
    TerminationDetails,
)

from dbxj.jobs import Job, JobsAPI, RunResult, classify_run


def status(
    state: RunLifecycleStateV2State | None = RunLifecycleStateV2State.TERMINATED,
    code: TerminationCodeCode | None = TerminationCodeCode.SUCCESS,
) -> RunStatus:
    details = TerminationDetails(code=code) if code is not None else None
    return RunStatus(state=state, termination_details=details)


def run(result: RunResult) -> BaseRun:
    codes = {
        RunResult.SUCCESS: TerminationCodeCode.SUCCESS,
        RunResult.FAILED: TerminationCodeCode.RUN_EXECUTION_ERROR,
        RunResult.CANCELLED: TerminationCodeCode.CANCELED,
    }
    if result == RunResult.RUNNING:
        return BaseRun(status=status(RunLifecycleStateV2State.RUNNING, None))
    return BaseRun(status=status(code=codes[result]))


@pytest.mark.parametrize(
    "run_status, expected",
    [
        (None, RunResult.FAILED),
        (status(state=None), RunResult.FAILED),
        (status(RunLifecycleStateV2State.RUNNING, None), RunResult.RUNNING),
        (status(RunLifecycleStateV2State.PENDING, None), RunResult.RUNNING),
        (status(RunLifecycleStateV2State.TERMINATING, None), RunResult.RUNNING),
        (status(code=None), RunResult.FAILED),
        (status(code=TerminationCodeCode.SUCCESS), RunResult.SUCCESS),
        (status(code=TerminationCodeCode.CANCELED), RunResult.CANCELLED),
        (status(code=TerminationCodeCode.USER_CANCELED), RunResult.CANCELLED),
        (status(code=TerminationCodeCode.SKIPPED), RunResult.CANCELLED),
        (status(code=TerminationCodeCode.RUN_EXECUTION_ERROR), RunResult.FAILED),
        (status(code=TerminationCodeCode.INTERNAL_ERROR), RunResult.FAILED),
    ],
)
def test_classify_run(run_status, expected):
    assert classify_run(run_status) == expected


@pytest.fixture
def ws_client():
    return MagicMock()


def test_get_api_jobs_skips_incomplete_and_escapes_markup(ws_client):
    ws_client.jobs.list.return_value = [
        BaseJob(job_id=1, settings=JobSettings(name="[dev] ingest")),
        BaseJob(job_id=None, settings=JobSettings(name="no id")),
        BaseJob(job_id=2, settings=None),
        BaseJob(job_id=3, settings=JobSettings(name="report")),
    ]
    api = JobsAPI(ws_client)
    assert list(api.get_jobs(clear_cache=True)) == [Job(1, r"\[dev] ingest"), Job(3, "report")]


def test_get_jobs_uses_cache_until_cleared(ws_client):
    ws_client.jobs.list.return_value = [BaseJob(job_id=1, settings=JobSettings(name="a"))]
    api = JobsAPI(ws_client)
    list(api.get_jobs(clear_cache=True))
    list(api.get_jobs())
    assert ws_client.jobs.list.call_count == 1

    list(api.get_jobs(clear_cache=True))
    assert ws_client.jobs.list.call_count == 2


def test_recent_runs_oldest_first_and_limited(ws_client):
    # The API returns newest first, and the iterator may yield more than limit
    newest_first = [RunResult.RUNNING, RunResult.FAILED, RunResult.SUCCESS, RunResult.CANCELLED]
    ws_client.jobs.list_runs.return_value = iter(run(r) for r in newest_first)
    api = JobsAPI(ws_client)
    assert api.get_recent_runs(1, n=3) == [RunResult.SUCCESS, RunResult.FAILED, RunResult.RUNNING]
    ws_client.jobs.list_runs.assert_called_once_with(job_id=1, limit=3)


def test_recent_runs_cached_per_job(ws_client):
    ws_client.jobs.list_runs.side_effect = lambda **_: iter([run(RunResult.SUCCESS)])
    api = JobsAPI(ws_client)
    assert api.get_recent_runs(1) == [RunResult.SUCCESS]
    assert api.get_recent_runs(1) == [RunResult.SUCCESS]
    assert api.get_recent_runs(2) == [RunResult.SUCCESS]
    assert ws_client.jobs.list_runs.call_count == 2


def test_recent_runs_none_from_api(ws_client):
    ws_client.jobs.list_runs.return_value = None
    assert JobsAPI(ws_client).get_recent_runs(1) == []


def test_recent_runs_failure_is_cached_until_refresh(ws_client):
    ws_client.jobs.list_runs.side_effect = PermissionError("denied")
    ws_client.jobs.list.return_value = []
    api = JobsAPI(ws_client)
    with pytest.raises(PermissionError):
        api.get_recent_runs(1)
    assert api.get_recent_runs(1) is None
    assert ws_client.jobs.list_runs.call_count == 1

    list(api.get_jobs(clear_cache=True))
    ws_client.jobs.list_runs.side_effect = None
    ws_client.jobs.list_runs.return_value = iter([run(RunResult.SUCCESS)])
    assert api.get_recent_runs(1) == [RunResult.SUCCESS]
