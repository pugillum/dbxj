from databricks.sdk import WorkspaceClient


def main():
    w = WorkspaceClient()

    job_name = "Test Job via SDK"
    for job in w.jobs.list():
        if job_name == job.settings.name:
            job_id = job.job_id
            break
    if job_id:
        w.jobs.run_now_and_wait(job_id)
    else:
        print("Job not found")
        raise RuntimeError("Job not found")


if __name__ == "__main__":
    main()
