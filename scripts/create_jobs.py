import argparse

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def main():
    # use argparse to parse command line arguments
    parser = argparse.ArgumentParser(description="Create a job")
    parser.add_argument("--count", type=int, default=1, help="Number of jobs to create")

    job_count = parser.parse_args().count
    for i in range(job_count):
        print(f"Creating job {i}")
        w.jobs.create(name=f"test_job{i}")


if __name__ == "__main__":
    main()
