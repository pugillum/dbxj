from enum import Enum
from itertools import islice
from typing import Dict, Iterator, List
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunLifecycleStateV2State, RunStatus, TerminationCodeCode

from dataclasses import dataclass


@dataclass
class Job:
    job_id: int
    job_name: str


class RunResult(Enum):
    SUCCESS = 0
    FAILED = 1
    RUNNING = 2
    CANCELLED = 3


CANCELLED_CODES = {
    TerminationCodeCode.CANCELED,
    TerminationCodeCode.USER_CANCELED,
    TerminationCodeCode.SKIPPED,
}


def classify_run(status: RunStatus | None) -> RunResult:
    if status is None or status.state is None:
        return RunResult.FAILED
    if RunLifecycleStateV2State(status.state) != RunLifecycleStateV2State.TERMINATED:
        return RunResult.RUNNING
    if status.termination_details is None or status.termination_details.code is None:
        return RunResult.FAILED
    code = TerminationCodeCode(status.termination_details.code)
    if code == TerminationCodeCode.SUCCESS:
        return RunResult.SUCCESS
    if code in CANCELLED_CODES:
        return RunResult.CANCELLED
    return RunResult.FAILED


class JobsAPI:
    jobs: List[Job] = []

    def __init__(self, ws_client: WorkspaceClient):
        self.ws_client = ws_client
        # None marks a failed fetch, so it isn't retried until the job list is refreshed
        self.recent_runs: Dict[int, List[RunResult] | None] = {}

    def get_api_jobs(self) -> None:
        self.jobs = []
        self.recent_runs = {}
        for job in self.ws_client.jobs.list():
            # # TODO: Temp for easy devevelopment - remove later
            # if job.job_id not in [676734171241441, 37206955666798]:
            #     continue

            if not job.job_id or not job.settings:
                continue

            name = str(job.settings.name)
            # escape square brackets otherwise rich will interpret them as style tags
            name = name.replace("[", r"\[")
            self.jobs.append(Job(job.job_id, name))

    def get_jobs(self, clear_cache: bool = False) -> Iterator[Job]:
        if clear_cache:
            self.get_api_jobs()
        for job in self.jobs:
            yield job

    def get_recent_runs(self, job_id: int, n: int = 5) -> List[RunResult] | None:
        """Results of the last n runs, oldest first, or None if the fetch failed.
        Cached until the job list is refreshed."""
        if job_id in self.recent_runs:
            return self.recent_runs[job_id]
        try:
            # The SDK iterator follows next_page_token, so limit is only the page size
            runs = islice(self.ws_client.jobs.list_runs(job_id=job_id, limit=n) or [], n)
            results = [classify_run(r.status) for r in runs]
        except Exception:
            self.recent_runs[job_id] = None
            raise
        results.reverse()
        self.recent_runs[job_id] = results
        return results
