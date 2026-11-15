import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from unittest.mock import MagicMock

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunLifecycleStateV2State, TerminationCodeCode


@dataclass
class JobSettings:
    name: str


@dataclass
class Job:
    job_id: int
    settings: JobSettings


@dataclass
class TerminationDetails:
    code: TerminationCodeCode


@dataclass
class RunStatus:
    state: RunLifecycleStateV2State
    termination_details: TerminationDetails | None


@dataclass
class JobRun:
    job_run_id: int
    start_time: int
    run_duration: int
    status: RunStatus


@dataclass
class ClusterInstance:
    cluster_id: str | None


@dataclass
class Task:
    task_key: str
    run_id: int | None
    run_duration: int | None
    status: RunStatus
    cluster_instance: ClusterInstance
    attempt_number: int | None


# TODO: Fix this in comparison to JobRun
@dataclass
class Run:
    tasks: list[Task]


@dataclass
class RunOutput:
    error: str | None
    error_trace: str | None
    logs: str | None


def data_dir() -> Path:
    """./cached if present (local development), otherwise the demo data bundled with the package."""
    cached = Path("cached")
    if cached.is_dir():
        return cached
    return Path(str(files("dbxj") / "sample_data"))


def parse_status(status_json: dict) -> RunStatus:
    # Runs that haven't finished have no termination details
    details = status_json.get("termination_details")
    return RunStatus(
        state=RunLifecycleStateV2State(status_json["state"]),
        termination_details=TerminationDetails(code=TerminationCodeCode(details["code"]))
        if details
        else None,
    )


class MockJobs:
    def __init__(self) -> None:
        self.data_dir = data_dir()

    def list(self):
        with open(self.data_dir / "jobs.json") as f:
            jobs_json = json.load(f)

        for j in jobs_json:
            job_setting = JobSettings(j["settings"]["name"])
            job = Job(j["job_id"], job_setting)
            yield job

    def list_runs(self, job_id: int, limit: int | None = None, **kwargs):
        # check if a file exists job_{job_id}.json
        # if it does, return the contents of that file
        # if it doesn't, return None
        job_file = self.data_dir / f"job_{job_id}.json"
        if job_file.exists():
            with open(job_file) as f:
                job_runs_json = json.load(f)

            # Need to return run ID, status, start time, and duration
            # Run ID is taken from job_run_id
            # Status looks at status.state and status.termination_details.code
            # Start time is taken from start_time
            # Duration is taken from run_duration
            for j in job_runs_json:
                job_run = JobRun(
                    job_run_id=j["job_run_id"],
                    start_time=j["start_time"],
                    run_duration=j.get("run_duration"),
                    status=parse_status(j["status"]),
                )
                yield job_run

        else:
            return None

    def get_run(self, run_id: int):
        # check if a file exists run_{run_id}.json
        # if it does, return the contents of that file
        # if it doesn't, return None
        run_file = self.data_dir / f"run_{run_id}.json"
        if run_file.exists():
            with open(run_file) as f:
                run_json = json.load(f)

            # Need to return task name, status, run ID, run duration, cluster ID, and attempts
            run = Run(tasks=[])
            for t in run_json["tasks"]:
                cluster_instance = ClusterInstance(cluster_id=t["cluster_instance"]["cluster_id"])
                run_duration = t["setup_duration"] + t["execution_duration"] + t["cleanup_duration"]
                task = Task(
                    task_key=t["task_key"],
                    run_id=t["run_id"],
                    run_duration=run_duration,
                    status=parse_status(t["status"]),
                    cluster_instance=cluster_instance,
                    attempt_number=t["attempt_number"],
                )
                run.tasks.append(task)
            return run

        else:
            return Run(tasks=[])

    def run_now(self, job_id: int, **kwargs):
        # mimics the SDK's Wait, which binds the new run_id
        wait = MagicMock()
        wait.bind.return_value = {"run_id": 1}
        return wait

    def get_run_output(self, run_id: int):
        # check if a file exists run_{run_id}_output.json
        # if it does, return the contents of that file
        # if it doesn't, return None
        run_output_file = self.data_dir / f"run_output_{run_id}.json"
        if run_output_file.exists():
            with open(run_output_file) as f:
                run_output_json = json.load(f)

            error = run_output_json.get("error")
            error_trace = run_output_json.get("error_trace")
            logs = run_output_json.get("logs")
            return RunOutput(
                error=error,
                error_trace=error_trace,
                logs=logs,
            )
        else:
            return RunOutput(error=None, error_trace=None, logs=None)


@dataclass
class User:
    user_name: str


class MockCurrentUser:
    def me(self):
        return User(user_name="demo.user@example.com")


def get_workspace_id():
    return 1234567890123456


def get_mock_client() -> WorkspaceClient:
    client = MagicMock(spec=WorkspaceClient)
    client.jobs = MockJobs()
    client.current_user = MockCurrentUser()
    client.get_workspace_id = get_workspace_id
    client.config = MagicMock(host="https://example.cloud.databricks.com")
    return client
