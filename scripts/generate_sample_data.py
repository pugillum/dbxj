"""Generate the fake workspace data used by `dbxj --offline` (src/dbxj/sample_data)."""

import json
import random
from pathlib import Path

OUT = Path(__file__).parent.parent / "src" / "dbxj" / "sample_data"
NOW = 1794981600000  # 2026-11-17 06:00 UTC, in ms
HOUR = 3_600_000
DAY = 24 * HOUR

# name, task keys, results of the most recent runs (newest first), hours between runs
JOBS = [
    ("daily_sales_ingest", ["extract", "transform", "load"], "SSSSSSSSSS", 24),
    ("customer_360_refresh", ["extract", "build_features", "publish"], "FSSFSSSSFS", 24),
    ("ml_churn_training", ["prepare_data", "train", "evaluate"], "RSSSSS", 168),
    ("[dev] nightly_cleanup", ["vacuum_tables"], "CSSCSSSS", 24),
    ("hourly_events_stream_check", ["check_lag"], "SSSFSSSSSSSSSSSSSSSS", 1),
    ("weekly_finance_report", ["aggregate", "render_report", "email"], "SS", 168),
    ("adhoc_backfill", ["backfill"], "", 0),
]

ERROR = (
    "AnalysisException: [TABLE_OR_VIEW_NOT_FOUND] The table or view `crm.contacts` cannot be found."
)
ERROR_TRACE = """---------------------------------------------------------------------------
AnalysisException                         Traceback (most recent call last)
File /Workspace/Repos/data/customer_360/build_features.py:42
     40 def main():
     41     spark = SparkSession.builder.getOrCreate()
---> 42     contacts = spark.table("crm.contacts")
     43     orders = spark.table("sales.orders")
     44     features = build(contacts, orders)

File /databricks/spark/python/pyspark/sql/session.py:1667, in SparkSession.table(self, tableName)
-> 1667     return DataFrame(self._jsparkSession.table(tableName), self)

AnalysisException: [TABLE_OR_VIEW_NOT_FOUND] The table or view `crm.contacts` cannot be found.
Verify the spelling and correctness of the schema and catalog."""

CODES = {"S": "SUCCESS", "F": "RUN_EXECUTION_ERROR", "C": "USER_CANCELED"}


def status(result: str) -> dict:
    if result == "R":
        return {"state": "RUNNING"}
    return {"state": "TERMINATED", "termination_details": {"code": CODES[result]}}


def task_results(result: str, count: int, failing_task: int) -> list[str]:
    """Tasks before the failing one succeed, the failing one fails/is cancelled/is running,
    and later ones are skipped (or haven't started)."""
    if result == "S":
        return ["S"] * count
    results = ["S"] * failing_task + [result]
    return results + ["K"] * (count - len(results))


def main() -> None:
    rng = random.Random(42)
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()

    jobs = []
    next_run_id = 500_000_000_000_000
    for job_index, (name, tasks, results, interval) in enumerate(JOBS):
        job_id = 100_000_000_000_000 + job_index * 7_919_000_000
        jobs.append({"job_id": job_id, "settings": {"name": name}})

        runs = []
        for i, result in enumerate(results):
            run_id = next_run_id
            next_run_id += rng.randint(1_000_000, 9_000_000)
            start = (
                NOW - i * interval * HOUR - rng.randint(0, 10) * 60_000 - (0 if i else DAY // 48)
            )
            failing_task = rng.randrange(len(tasks)) if name != "customer_360_refresh" else 1

            task_runs = []
            elapsed = 0
            for t_index, (task_key, t_result) in enumerate(
                zip(tasks, task_results(result, len(tasks), failing_task))
            ):
                task_run_id = run_id + t_index + 1
                if t_result == "K":  # skipped / not started
                    t_status = (
                        {"state": "PENDING"}
                        if result == "R"
                        else {"state": "TERMINATED", "termination_details": {"code": "SKIPPED"}}
                    )
                    setup = execution = cleanup = 0
                else:
                    t_status = status(t_result)
                    setup = rng.randint(5, 90) * 1000
                    execution = rng.randint(30, 1200) * 1000
                    cleanup = rng.randint(1, 10) * 1000
                    if t_result == "R":
                        execution, cleanup = NOW - start - elapsed - setup, 0
                elapsed += setup + execution + cleanup
                task_runs.append(
                    {
                        "task_key": task_key,
                        "run_id": task_run_id,
                        "attempt_number": 1 if t_result != "F" else 2,
                        "setup_duration": setup,
                        "execution_duration": execution,
                        "cleanup_duration": cleanup,
                        "status": t_status,
                        "cluster_instance": {
                            "cluster_id": f"1117-0600{job_index:02}-demo{job_index:04}"
                        },
                    }
                )
                write_output(task_run_id, task_key, t_result)

            run = {"job_run_id": run_id, "start_time": start, "status": status(result)}
            if result != "R":
                run["run_duration"] = elapsed
            runs.append(run)
            write(f"run_{run_id}.json", {"tasks": task_runs})

        if runs:
            write(f"job_{job_id}.json", runs)

    write("jobs.json", jobs)


def write_output(task_run_id: int, task_key: str, result: str) -> None:
    if result == "F":
        output = {"error": ERROR, "error_trace": ERROR_TRACE}
    elif result == "S":
        output = {"logs": f"Starting {task_key}\nProcessed 12,345 rows\n{task_key} finished\n"}
    else:
        return
    write(f"run_output_{task_run_id}.json", output)


def write(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
