from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def main():
    # use argparse to parse command line arguments
    for j in w.jobs.list():
        if j.settings.name.startswith("test_job"):
            print(f"Deleting job {j.job_id}")
            w.jobs.delete(j.job_id)


if __name__ == "__main__":
    main()
