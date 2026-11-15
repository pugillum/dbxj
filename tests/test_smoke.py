"""Drive the app against the bundled demo data, without a workspace."""

import pytest
from textual.widgets import DataTable, Static

from dbxj.body import Body, BodyState
from dbxj.main import DbxjApp, MainScreen
from dbxj.mock_workspace_client import data_dir


@pytest.fixture(autouse=True)
def use_bundled_data(tmp_path, monkeypatch):
    # Run outside the repo so a local ./cached directory isn't picked up
    monkeypatch.chdir(tmp_path)


async def wait_for_rows(pilot, table: DataTable) -> None:
    for _ in range(100):
        await pilot.pause(0.05)
        if table.row_count and not table.loading:
            return
    raise AssertionError("table never filled")


def test_bundled_data_is_used():
    assert data_dir().name == "sample_data"


async def test_drill_into_failed_task():
    app = DbxjApp(offline=True)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.5)
        assert isinstance(app.screen, MainScreen)
        body = app.screen.query_one(Body)
        table = body.query_one("#table", DataTable)
        await wait_for_rows(pilot, table)
        assert table.row_count == 7

        # customer_360_refresh: its latest run failed in build_features
        table.move_cursor(row=table.get_row_index("100007919000000"))
        await pilot.press("enter")
        await wait_for_rows(pilot, table)
        assert body.state == BodyState.JOB_RUNS
        assert "RUN_EXECUTION_ERROR" in str(table.get_row_at(0))

        await pilot.press("enter")
        await wait_for_rows(pilot, table)
        assert body.state == BodyState.JOB_RUN
        assert table.row_count == 3

        table.move_cursor(row=1)
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert body.state == BodyState.TASK
        details = str(body.query_one("#details_panel_label", Static).render())
        assert "TABLE_OR_VIEW_NOT_FOUND" in details

        for _ in range(3):
            await pilot.press("escape")
        await wait_for_rows(pilot, table)
        assert body.state == BodyState.JOBS
