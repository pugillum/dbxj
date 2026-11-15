from databricks.sdk.service.jobs import RunLifecycleStateV2State, TerminationCodeCode

from dbxj.mock_workspace_client import data_dir, get_mock_client, parse_status


def test_parse_status_terminated():
    status = parse_status({"state": "TERMINATED", "termination_details": {"code": "SUCCESS"}})
    assert status.state == RunLifecycleStateV2State.TERMINATED
    assert status.termination_details is not None
    assert status.termination_details.code == TerminationCodeCode.SUCCESS


def test_parse_status_running():
    status = parse_status({"state": "RUNNING"})
    assert status.state == RunLifecycleStateV2State.RUNNING
    assert status.termination_details is None


def test_data_dir_prefers_local_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert data_dir().name == "sample_data"
    (tmp_path / "cached").mkdir()
    assert data_dir().resolve() == (tmp_path / "cached").resolve()


def test_mock_client_missing_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = get_mock_client()
    assert list(client.jobs.list_runs(job_id=1)) == []
    assert client.jobs.get_run(1).tasks == []
    assert client.jobs.get_run_output(1).error is None


def test_mock_client_bundled_data_is_consistent(tmp_path, monkeypatch):
    # Every job, run and task in the bundled demo data should load without error
    monkeypatch.chdir(tmp_path)
    client = get_mock_client()
    jobs = list(client.jobs.list())
    assert jobs
    for job in jobs:
        for run in client.jobs.list_runs(job_id=job.job_id):
            for task in client.jobs.get_run(run.job_run_id).tasks:
                assert task.task_key
                client.jobs.get_run_output(task.run_id)
