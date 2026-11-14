# just run <profile>, or just run for the default profile
run profile="":
    uv run dbxj {{ if profile != "" { "--profile " + profile } else { "" } }}

run_offline:
    uv run dbxj --offline

setup_python:
    uv venv --python 3.11
    uv sync

upgrade_and_sync:
    uv upgrade
    uv sync

sync: # adds all packages to .venv
    uv sync

create_jobs:
    uv run ./scripts/create_jobs.py --count 10

create_jobs_50:
    uv run ./scripts/create_jobs.py --count 50

delete_jobs:
    uv run ./scripts/delete_jobs.py

install:
    uv tool install --reinstall .
