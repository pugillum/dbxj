# Changelog

## 0.1.1

- Fix startup crash with Textual 8 (`Label(renderable=...)` was removed)
- Declare tested dependency ranges (`textual>=3,<9`, `databricks-sdk>=0.49`)

## 0.1.0

First public release.

- Browse jobs, their runs, the tasks in a run and task output/error traces
- `Last 5` column with the results of each job's recent runs
- Filter jobs by name, trigger a job, open the selection in the browser
- Profile selection (`--profile` / `DATABRICKS_CONFIG_PROFILE`) and in-app re-login when the
  session has expired
- `--offline` / `--demo` mode with bundled demo data
