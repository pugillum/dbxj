import argparse
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import SparkPythonTask, Task
from databricks.sdk.service.workspace import ImportFormat, Language


def get_job_id(w: WorkspaceClient, job_name: str) -> int | None:
    for job in w.jobs.list():
        if job_name == job.settings.name:
            return job.job_id
    return None


def main():
    # copy job.py file to workspace
    # CLI databricks workspace import /job.py --file job.py --language PYTHON --format SOURCE --overwrite
    parser = argparse.ArgumentParser(description="Create a test job that runs job.py")
    parser.add_argument("--cluster-id", required=True, help="Existing cluster to run the task on")
    cluster_id = parser.parse_args().cluster_id

    w = WorkspaceClient()
    with open(Path(__file__).parent / "job.py", "r") as f:
        content = f.read()

    w.workspace.mkdirs("/Shared/Scripts")

    w.workspace.upload(
        path="/Shared/Scripts/job.py",
        content=content,
        format=ImportFormat.RAW,
        language=Language.PYTHON,
        overwrite=True,
    )

    spark_python_task = SparkPythonTask(
        python_file="/Shared/Scripts/job.py",
        parameters=[],
    )
    task = Task(
        task_key="test",
        existing_cluster_id=cluster_id,
        spark_python_task=spark_python_task,
    )

    job_name = "Test Job via SDK"
    job_id = get_job_id(w, job_name)
    if job_id:
        job_settings = w.jobs.get(job_id).settings
        job_settings.tasks = [task]
        w.jobs.reset(job_id, job_settings)
    else:
        w.jobs.create(name=job_name, tasks=[task])


if __name__ == "__main__":
    main()
