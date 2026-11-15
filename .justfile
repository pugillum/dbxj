# just run <profile>, or just run for the default profile
run profile="":
    uv run dbxj {{ if profile != "" { "--profile " + profile } else { "" } }}

run_offline:
    uv run dbxj --offline

pre_commit:
    uv run pre-commit run --all-files

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

check: # same as CI (locked deps)
    uv sync --locked
    uv run ruff check
    uv run ruff format --check
    uv run ty check
    uv run pytest

check_lowest: # oldest allowed dependency versions
    cp uv.lock uv.lock.bak
    uv sync --resolution lowest-direct
    uv run pytest
    mv uv.lock.bak uv.lock
    uv sync --locked

check_latest: # newest dependency versions (what `uv tool install` resolves)
    cp uv.lock uv.lock.bak
    uv sync --upgrade
    uv run pytest
    mv uv.lock.bak uv.lock
    uv sync --locked

check_all: check check_lowest check_latest

test_install: # build the wheel and install it like a user would
    rm -rf dist
    uv build
    uv tool install --reinstall dist/*.whl
    dbxj --demo
