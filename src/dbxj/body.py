from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from enum import Enum
from itertools import islice
from typing import ClassVar

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import RunLifecycleStateV2State, TerminationCodeCode
from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import CellDoesNotExist, RowDoesNotExist
from textual.worker import get_current_worker

from dbxj.dialogs import ConfirmScreen
from dbxj.jobs import JobsAPI, RunResult

RECENT_RUNS = 5
RUN_SYMBOLS = {
    RunResult.SUCCESS: ("✓", "green"),
    RunResult.FAILED: ("✗", "red"),
    RunResult.RUNNING: ("●", "yellow"),
    RunResult.CANCELLED: ("⊘", "grey50"),
}


def render_recent_runs(results: list[RunResult] | None) -> Text:
    """Oldest to newest, left padded with '-' when there are fewer than RECENT_RUNS runs.
    None means the fetch failed."""
    if results is None:
        return Text("?", style="red")
    text = Text()
    for _ in range(RECENT_RUNS - len(results)):
        text.append("- ", style="dim")
    for result in results:
        symbol, style = RUN_SYMBOLS[result]
        text.append(symbol + " ", style=style)
    text.rstrip()
    return text


def format_start_time(ms: int | None) -> str:
    """Epoch milliseconds as local time."""
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(ms: int | None) -> str:
    """Milliseconds as e.g. '45s', '12m 34s', '2h 05m 10s', '1d 03h 12m'.
    None (still running) shows as '-'."""
    if ms is None:
        return "-"
    seconds = ms // 1000
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours:02}h {minutes:02}m"
    if hours:
        return f"{hours}h {minutes:02}m {seconds:02}s"
    if minutes:
        return f"{minutes}m {seconds:02}s"
    return f"{seconds}s"


class BodyState(Enum):
    JOBS = 0
    JOB_RUNS = 1
    JOB_RUN = 2
    TASK = 3


class FilterState(Enum):
    NONE = 0
    TYPING = 1
    SELECTING = 2


class DataTablePlus(DataTable, can_focus=True):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "scroll_left", "Scroll left", show=False),
        Binding("l", "scroll_right", "Scroll right", show=False),
        Binding("u", "page_up", "Page up", show=False),
        Binding("d", "page_down", "Page down", show=False),
        Binding("<", "scroll_top", "Top", show=False),
        Binding(">", "scroll_bottom", "Bottom", show=False),
    ]


class VerticalScrollPlus(VerticalScroll):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
        Binding("d", "page_down", "Page down", show=False),
        Binding("u", "page_up", "Page up", show=False),
        Binding("g", "scroll_home", "Scroll home", show=False),
        Binding("G", "scroll_end", "Scroll end", show=False),
    ]


class DetailsPanel(Widget, can_focus=True):
    def compose(self) -> ComposeResult:
        yield VerticalScrollPlus(Static(id="details_panel_label"), id="details_panel_scroll")


class FilterPanel(Widget, can_focus=True):
    filter_input: Input

    def __init__(self, **kwargs) -> None:
        self.filter_input = Input(id="filter_input", placeholder="Filter jobs by name")
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield self.filter_input

    def clear(self) -> None:
        self.filter_input.clear()

    def set_select_message(self, message: str) -> None:
        self.filter_input.value = message

    def focus_input(self) -> None:
        self.filter_input.focus()


class Body(Widget):
    state = BodyState.JOBS
    filter_state = FilterState.NONE
    jobs_initialised = False
    # the text being filtered on once the filter is in SELECTING (the input then shows "Matches for")
    job_filter = ""
    current_job_id: str | None = None
    current_job_key: str | None = None
    current_run_id: str | None = None
    current_run_key: str | None = None
    current_task_run_id: str | None = None
    current_task_url: str | None = None
    workspace_id: int | None = None
    # run page URLs for rows in the runs and tasks tables, keyed by row key
    row_urls: dict[str, str]
    data_table: DataTablePlus
    details_panel: Widget
    filter_panel: FilterPanel

    def compose(self) -> ComposeResult:
        with Vertical():
            yield FilterPanel(id="filter_panel")
            yield DataTablePlus(show_header=True, show_cursor=True, id="table", cursor_type="row")
            yield DetailsPanel(id="details_panel")

    class JobsInitialised(Message):
        pass

    def initialise(self, ws_client: WorkspaceClient, workspace_id: int | None = None) -> None:
        self.ws_client = ws_client
        self.workspace_id = workspace_id
        self.jobs_api = JobsAPI(ws_client)
        self.row_urls = {}
        self.data_table = self.query_one(DataTablePlus)
        self.details_panel = self.query_one(DetailsPanel)
        self.details_panel.display = False
        self.filter_panel = self.query_one(FilterPanel)
        self.filter_panel.display = False
        self.state = BodyState.JOBS
        self.load_jobs()

    def show_filter(self) -> None:
        self.filter_state = FilterState.TYPING
        self.filter_panel.display = True
        self.filter_panel.focus()
        self.filter_panel.focus_input()

    def hide_filter(self) -> None:
        self.filter_state = FilterState.NONE
        self.job_filter = ""
        self.filter_panel.display = False
        self.filter_panel.clear()

    def active_filter(self) -> str:
        if self.filter_state == FilterState.TYPING:
            return self.filter_panel.filter_input.value
        return self.job_filter

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            if self.state == BodyState.JOBS and self.filter_state != FilterState.NONE:
                self.hide_filter()
                self.load_jobs(select_key=self.cursor_row_key())
                self.data_table.focus()
            if self.state == BodyState.JOB_RUNS:  # looking at runs for a job
                self.state = BodyState.JOBS
                self.table_loading()
                # the filter is kept while drilled in, so bring it back
                self.filter_panel.display = self.filter_state != FilterState.NONE
                self.load_jobs(filter=self.job_filter, select_key=self.current_job_key)
            elif self.state == BodyState.JOB_RUN:  # looking at the tasks in a job run
                self.state = BodyState.JOB_RUNS
                self.table_loading()
                self.load_job_runs(self.current_job_id, select_key=self.current_run_key)
            elif self.state == BodyState.TASK:  # looking at specific task status/logs
                self.state = BodyState.JOB_RUN
                self.table_loading()
                self.details_panel.display = False
                self.data_table.display = True
                self.load_job_run(self.current_run_id, select_key=str(self.current_task_run_id))
        elif event.key == "slash":
            if self.state == BodyState.JOBS:
                self.show_filter()
        elif (
            event.key == "enter"
            and self.state == BodyState.JOBS
            and self.filter_state == FilterState.TYPING
        ):
            event.stop()  # prevent row selection in table
            self.data_table.focus()
            self.job_filter = self.filter_panel.filter_input.value
            self.filter_state = FilterState.SELECTING
            self.filter_panel.set_select_message(f"Matches for '{self.job_filter}'")

    def cursor_row_key(self) -> str | None:
        if self.data_table.row_count == 0:
            return None
        return self.data_table.ordered_rows[self.data_table.cursor_row].key.value

    def select_row(self, key: str | None) -> None:
        if key is None:
            return
        try:
            self.data_table.move_cursor(row=self.data_table.get_row_index(key))
        except RowDoesNotExist:
            pass  # row filtered out or gone since the last load

    def refresh_view(self) -> None:
        """Reload whatever is on screen, keeping the cursor on the same row."""
        if not self.jobs_initialised:
            return
        if self.state == BodyState.TASK:
            self.details_panel.loading = True
            self.load_task_logs(self.current_task_run_id)
            return

        select_key = self.cursor_row_key()
        self.table_loading()
        if self.state == BodyState.JOBS:
            self.load_jobs(
                filter=self.active_filter(),
                focus=self.filter_state != FilterState.TYPING,
                clear_cache=True,
                select_key=select_key,
            )
        elif self.state == BodyState.JOB_RUNS:
            self.load_job_runs(self.current_job_id, select_key=select_key)
        elif self.state == BodyState.JOB_RUN:
            self.load_job_run(self.current_run_id, select_key=select_key)

    def job_url(self, job_id: int | str | None, run_id: int | str | None = None) -> str:
        url = f"{self.ws_client.config.host.rstrip('/')}/jobs/{job_id}"
        if run_id is not None:
            url += f"/runs/{run_id}"
        if self.workspace_id:
            url += f"?o={self.workspace_id}"
        return url

    def open_in_browser(self) -> None:
        if not self.jobs_initialised:
            return
        if self.state == BodyState.TASK:
            url = self.current_task_url
        else:
            key = self.cursor_row_key()
            if key is None:
                return
            if self.state == BodyState.JOBS:
                url = self.job_url(key)
            else:
                url = self.row_urls.get(key) or self.job_url(self.current_job_id, key)
        if url:
            self.app.open_url(url)

    def trigger_job(self) -> None:
        if self.state != BodyState.JOBS or not self.jobs_initialised:
            return
        key = self.cursor_row_key()
        if key is None:
            return
        job_id, job_name = self.data_table.get_row(key)[:2]

        def confirmed(run: bool | None) -> None:
            if run:
                self.run_job(job_id, job_name)

        self.app.push_screen(ConfirmScreen("Trigger job", f"Run [b]{job_name}[/] now?"), confirmed)

    @work(thread=True, group="trigger")
    def run_job(self, job_id: int, job_name: str) -> None:
        try:
            # don't wait for the run to finish, only for it to be created
            run_id = self.ws_client.jobs.run_now(job_id=job_id).bind()["run_id"]
        except Exception as e:  # noqa: BLE001 - report any failure instead of crashing the worker
            self.app.call_from_thread(
                self.notify, f"Failed to trigger {job_name}: {e}", severity="error"
            )
            return
        self.app.call_from_thread(self.notify, f"Triggered {job_name} (run {run_id})")

        self.jobs_api.recent_runs.pop(job_id, None)
        try:
            cell = render_recent_runs(self.jobs_api.get_recent_runs(job_id, RECENT_RUNS))
        except Exception:  # noqa: BLE001 - show the cell as failed
            cell = render_recent_runs(None)
        self.app.call_from_thread(self.set_recent_runs_cell, job_id, cell)

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter_input":
            self.log.warning(f"Unexpected input changed from {event.input.id}")
            return

        # This is also triggered when the filter is cleared
        if self.filter_state == FilterState.TYPING:
            self.load_jobs(filter=event.input.value, focus=False)

    @work(exclusive=True, thread=True)
    async def load_jobs(
        self,
        filter: str = "",
        focus: bool = True,
        clear_cache: bool = False,
        select_key: str | None = None,
    ) -> None:
        self.data_table.clear(columns=True)
        self.data_table.add_column("Job ID", key="job_id")
        self.data_table.add_column("Job Name", key="job_name")
        # fixed width: update_cell doesn't grow the column as the "…" placeholders fill in
        self.data_table.add_column(
            f"Last {RECENT_RUNS}", key="recent_runs", width=2 * RECENT_RUNS - 1
        )

        if not self.jobs_initialised:  # TODO: Replace this clunkiness
            clear_cache = True

        to_fetch = []
        for job in self.jobs_api.get_jobs(clear_cache=clear_cache):
            if filter and filter.lower() not in job.job_name.lower():
                continue
            if job.job_id in self.jobs_api.recent_runs:
                cell = render_recent_runs(self.jobs_api.recent_runs[job.job_id])
            else:
                cell = Text("…", style="dim")
                to_fetch.append(job.job_id)
            self.data_table.add_row(job.job_id, job.job_name, cell, key=str(job.job_id))

        self.data_table.sort("job_name")
        self.app.call_from_thread(self.select_row, select_key)
        self.app.call_from_thread(self.load_recent_runs, to_fetch)

        self.data_table.loading = False
        if focus:
            self.data_table.focus()

        # signal that jobs have been loaded if not already done
        if not self.jobs_initialised:
            self.post_message(self.JobsInitialised())
            self.jobs_initialised = True

    @work(exclusive=True, thread=True, group="recent_runs")
    def load_recent_runs(self, job_ids: list[int]) -> None:
        # One list_runs call per job (there's no batched public API); results fill in as they arrive
        worker = get_current_worker()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(self.jobs_api.get_recent_runs, j, RECENT_RUNS): j for j in job_ids
            }
            for future in as_completed(futures):
                if worker.is_cancelled or self.state != BodyState.JOBS:
                    pool.shutdown(cancel_futures=True)
                    return
                try:
                    cell = render_recent_runs(future.result())
                except Exception as e:  # noqa: BLE001 - show the cell as failed
                    self.log.warning(f"Recent runs for {futures[future]} failed: {e}")
                    cell = render_recent_runs(None)
                self.app.call_from_thread(self.set_recent_runs_cell, futures[future], cell)

    def set_recent_runs_cell(self, job_id: int, cell: Text) -> None:
        if self.state != BodyState.JOBS:
            return
        try:
            self.data_table.update_cell(str(job_id), "recent_runs", cell)
        except (CellDoesNotExist, RowDoesNotExist):
            pass  # row filtered out or table reloaded

    @work(exclusive=True, thread=True)
    async def load_job_runs(self, job_id: int, select_key: str | None = None) -> None:
        self.data_table.clear(columns=True)
        self.data_table.add_columns(*("Run ID", "Status", "Start Time", "Duration"))
        self.row_urls = {}
        limit = 25
        # TODO: drop islice when the API limit actually works
        for r in islice(self.ws_client.jobs.list_runs(job_id=job_id, limit=limit) or [], limit):
            status = "Unknown"
            if r.status is None:
                status = "Unknown"
            elif r.status.state != RunLifecycleStateV2State.TERMINATED:
                status = RunLifecycleStateV2State(r.status.state).name
            elif r.status.termination_details:
                status = TerminationCodeCode(r.status.termination_details.code).name
            else:
                status = "Unknown"
            key = str(r.job_run_id)
            self.data_table.add_row(
                r.job_run_id,
                status,
                format_start_time(r.start_time),
                format_duration(r.run_duration),
                key=key,
            )
            if url := getattr(r, "run_page_url", None):
                self.row_urls[key] = url

        self.app.call_from_thread(self.select_row, select_key)
        self.data_table.loading = False
        self.data_table.focus()

    # load job run
    @work(exclusive=True, thread=True)
    async def load_job_run(self, run_id: int, select_key: str | None = None) -> None:
        self.data_table.clear(columns=True)
        self.data_table.add_columns(
            *("Run ID", "Task Name", "Status", "Run Duration", "Cluster ID", "Attempts")
        )
        self.row_urls = {}
        run = self.ws_client.jobs.get_run(run_id)
        if run is None:
            return

        if run.tasks is None:
            return

        for task in run.tasks:
            status = "Unknown"
            if task.status is None:
                status = "Unknown"
            elif task.status.state != RunLifecycleStateV2State.TERMINATED:
                status = RunLifecycleStateV2State(task.status.state).name
            elif task.status.termination_details:
                status = TerminationCodeCode(task.status.termination_details.code).name
            else:
                status = "Unknown"

            if task.cluster_instance:
                cluster_instance = task.cluster_instance.cluster_id
            else:
                cluster_instance = "Unknown"

            key = str(task.run_id)
            self.data_table.add_row(
                task.run_id,
                task.task_key,
                status,
                format_duration(task.run_duration),
                cluster_instance,
                task.attempt_number,
                key=key,
            )
            if url := getattr(task, "run_page_url", None):
                self.row_urls[key] = url

        self.app.call_from_thread(self.select_row, select_key)
        self.data_table.loading = False
        self.data_table.focus()

    @work(exclusive=True, thread=True)
    async def load_task_logs(self, run_id: int) -> None:
        task = self.ws_client.jobs.get_run_output(run_id)
        error = task.error

        if error:
            error_trace = task.error_trace
            job_text = error + "\n" + str(error_trace)
            text_obj = Text(job_text)  # because of ANSI colors
            self.query_one("#details_panel_label", Static).update(text_obj)
        else:
            text_obj = Text(task.logs) if task.logs is not None else Text("")
            self.query_one("#details_panel_label", Static).update(text_obj)
        self.details_panel.loading = False
        self.query_one("#details_panel_scroll", VerticalScrollPlus).focus()

    # This needs to happen before calling threaded functions otherwise errors occur
    def table_loading(self) -> None:
        self.data_table.clear(columns=True)
        self.data_table.loading = True

    def on_data_table_row_selected(self, message: DataTablePlus.RowSelected) -> None:
        if self.state == BodyState.JOBS:
            # keep the filter so it's still applied when coming back with esc
            self.filter_panel.display = False
            self.state = BodyState.JOB_RUNS
            job_id = message.data_table.get_row(message.row_key)[0]
            self.current_job_id = job_id
            self.current_job_key = message.row_key.value
            self.log.info(f"Row selected: {job_id}")
            self.table_loading()
            self.load_job_runs(job_id)
        elif self.state == BodyState.JOB_RUNS:
            self.state = BodyState.JOB_RUN
            run_id = message.data_table.get_row(message.row_key)[0]
            self.current_run_id = run_id
            self.current_run_key = message.row_key.value
            self.log.info(f"Row selected: {run_id}")
            self.table_loading()
            self.load_job_run(run_id)
        elif self.state == BodyState.JOB_RUN:
            self.state = BodyState.TASK
            run_id = message.data_table.get_row(message.row_key)[0]
            self.current_task_run_id = run_id
            key = str(message.row_key.value)
            self.current_task_url = self.row_urls.get(key) or self.job_url(self.current_job_id, key)
            self.log.info(f"Row selected: {run_id}")
            self.details_panel.loading = True
            self.data_table.display = False
            self.details_panel.display = True
            self.load_task_logs(run_id)
