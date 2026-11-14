# Design

`dbxj` is a terminal UI for browsing Databricks jobs, their runs, the tasks in a run and task output.
It's built on [Textual](https://textual.textualize.io/) and the
[Databricks Python SDK](https://github.com/databricks/databricks-sdk-py).

## Style: minimal TUI like lazygit and k9s

`dbxj` should look and feel like [lazygit](https://github.com/jesseduffield/lazygit) and
[k9s](https://k9scli.io/), not like a typical Textual app. Every UI change must follow these rules:

- **Keyboard only.** Every action is a single key (`t`, `o`, `r`, `/`, ...) with vim-style
  navigation (`j`/`k`, `d`/`u`). There are no buttons, checkboxes or clickable widgets, and nothing
  that needs the mouse.
- **Plain bordered panels.** Use `solid white` borders on the default background. Put titles and key
  hints in the border (`border_title` / `border_subtitle`, e.g. `y confirm · n cancel`), not in extra
  widgets. Don't add Textual's stock look: no themed dialog boxes, header bars or coloured
  backgrounds.
- **Popups are overlays.** Dialogs, confirmations and help are a small centred box on a
  `ModalScreen` over the current view (see `dialogs.py`). `esc` always closes them. `y`/`n` answers
  confirmations. Textual's default dimming of the screen behind a modal is turned off
  (`background: transparent`). The box itself is opaque (`background: $background`), so the table
  doesn't show through.
- **Dense, text-first content.** Prefer tables and compact symbols (`✓ ✗ ● ⊘`) with sparing colour
  (green/red/yellow/grey for state, yellow for keys). Don't use decorative padding or spacing.
- **One bottom bar.** `StatusBar` (`main.py`) holds the key hints on the left and a brief status
  message on the right, like lazygit. The hints are only the essential keys (`r` refresh, `q` quit,
  `?` help). Every other binding uses `show=False` and is listed in the `?` help overlay. The `^p`
  command palette hint is hidden too, though `ctrl+p` still works.
- **Feedback is a status message, never an overlay.** `DatabricksTUI.notify` is overridden, so every
  `notify()` call writes one line into the bottom bar instead of showing Textual's toast cards.
  Messages are green / yellow / red for information / warning / error and clear themselves after
  4s, or 8s for errors. Use a popup only when the user has to make a decision.
- **No scrollbars.** A global `* { scrollbar-size: 0 0; }` in `main.tcss` hides them. In a narrow or
  short window the content is clipped like in k9s and scrolled with keys (`j`/`k`, `d`/`u`, and
  `h`/`l` or arrows to pan wide tables).
- **Restyle stock Textual widgets rather than accepting their defaults.** Check new widgets against
  these rules. Textual's `DEFAULT_CSS` is overridden by `main.tcss`.

## Principles

- **`q` / `esc` always work**, including while waiting on something slow (e.g. browser login).
- **Destructive or costly actions ask first**, e.g. `t` triggering a job shows a y/n popup.
- **Never block the UI thread**: API calls run in Textual workers (`@work(thread=True)` or
  `asyncio.to_thread`).

## Layout

```
src/dbxj/
  main.py                    entry point, arg parsing, App, MainScreen, SplashScreen, Header
  body.py                    Body widget: table/filter/details panels and the navigation state machine
  jobs.py                    JobsAPI: cached job list
  auth.py                    profiles, connection check, ReauthScreen
  dialogs.py                 HelpScreen (? overlay), ConfirmScreen (y/n popup)
  mock_workspace_client.py   offline client backed by ./cached/*.json or sample_data/*.json
  sample_data/               fake workspace for --offline/--demo (scripts/generate_sample_data.py)
  main.tcss                  styles
```

## Startup flow

1. `main()` parses `--profile` (default `DATABRICKS_CONFIG_PROFILE`), `--offline` (alias `--demo`)
   and `--version`. An unknown
   profile exits with the list from `~/.databrickscfg` (or `DATABRICKS_CONFIG_FILE`).
2. `DatabricksTUI` pushes `MainScreen`, then `SplashScreen` on top.
3. `MainScreen.setup_client` (async worker) calls `auth.connect(profile)` in a thread. It builds a
   `WorkspaceClient` and calls `current_user.me()` / `get_workspace_id()` to prove the login is valid.
4. On `AuthError` it awaits `ReauthScreen` (see below). If login succeeds it loops back to step 3;
   if the user quits, the app exits.
5. `Header` and `Body` are initialised. When the first job list loads, `Body` posts
   `JobsInitialised` and the app pops the splash screen.

Offline mode skips 3–4 and uses `get_mock_client()`. It reads `./cached` if that directory exists
(for local development against captured data), otherwise the fake workspace bundled in
`dbxj/sample_data`, so `dbxj --demo` works after a plain install. `tests/test_smoke.py` drives the
app against that data.

## Re-authentication

All profiles are expected to use `auth_type = databricks-cli` (OAuth U2M), so re-auth shells out to
`databricks auth login --profile <p>`. The CLI opens the browser and blocks until the OAuth callback.

`ReauthScreen` (a `ModalScreen[bool]`):
- starts the login as soon as it mounts, with output captured so it can't corrupt the TUI
- `q` / `esc` terminates the login process and dismisses with `False`
- on failure it shows stderr; `enter` / `r` retries
- any exception from `connect` is treated as an auth failure; the error text is shown so network
  problems can be told apart

## Navigation state machine (`body.py`)

`BodyState`: `JOBS` → `JOB_RUNS` → `JOB_RUN` (tasks) → `TASK` (logs). `enter` drills in, `esc` goes
back. Each level clears the shared `DataTablePlus` and reloads it in a worker. `TASK` hides the table
and shows `DetailsPanel`, a scrollable view of the run output with ANSI colours.

`FilterState`: `NONE` → `TYPING` (`/` opens the filter input; the table filters live) → `SELECTING`
(`enter` moves focus back to the table and saves the text in `Body.job_filter`). Only available in
`JOBS`. Drilling into a job only hides the filter panel; `esc` back to `JOBS` shows it again and
reapplies `job_filter`. `esc` in `JOBS` clears the filter.

Tables key their rows by job / run id. Going back with `esc` puts the cursor back on the row that
was drilled into (`current_job_key`, `current_run_key`, `current_task_run_id`), via the loaders'
`select_key` argument.

## Actions

Bound on `MainScreen` and delegated to `Body`:

- `r` → `Body.refresh_view`: reloads the current view (jobs with the cache cleared and the filter
  kept, runs, tasks, or the task logs), keeping the cursor on the same row.
- `t` → `Body.trigger_job`: jobs view only. It shows a `ConfirmScreen`, then `jobs.run_now` in a
  worker. It doesn't wait on the returned `Wait`; the new run id comes from `.bind()["run_id"]`. A
  status message in the bottom bar reports the result, and the job's `Last 5` cell is refetched.
- `o` → `Body.open_in_browser` → `App.open_url`. Jobs use `{host}/jobs/{id}?o={workspace_id}`. Runs
  and tasks use the API's `run_page_url`, with a fallback of `{host}/jobs/{job}/runs/{run}?o=...`.
- `?` → `HelpScreen`, a static key list in `dialogs.HELP_SECTIONS`. Most navigation keys are
  handled in `Body.on_key` rather than as `Binding`s, so they can't be generated.

Single-letter screen bindings don't fire while typing in the filter, because `Input` consumes
printable keys.

## Last 5 runs column

The jobs table has a `Last 5` column, ordered oldest → newest: `✓` success, `✗` failed, `●` running/
queued, `⊘` cancelled/skipped, `-` no run, `?` fetch failed, `…` loading.

The public Jobs API can't return recent runs for many jobs in one call. `jobs.list` has no runs
option and `jobs.list_runs` takes a single `job_id`. The portal uses an internal GraphQL route
(`/graphql/LakeflowListAssetsQuery`) that only accepts browser session cookies: bearer tokens get a
303 to the login page (tested 2026-11-14), so we can't use it. Instead `Body.load_recent_runs` makes one
`list_runs(job_id, limit=5)` per job on an 8-thread pool. The table renders at once and cells fill in
as results arrive. The SDK iterator follows `next_page_token`, so `JobsAPI.get_recent_runs` caps the
results with `islice`. The column has a fixed width (`2 * RECENT_RUNS - 1`): `update_cell` doesn't resize a column, so
sizing it from the `…` placeholders cut cells off at 3 symbols. Results (including failures) are cached in `JobsAPI.recent_runs`, so filtering
doesn't refetch. `r` clears the cache.

## Packaging

- The package and command are both `dbxj` (`[project.scripts] dbxj = "dbxj.main:main"`), installed
  with `uv tool install .`.
- Runtime deps are only `databricks-sdk` and `textual`; tooling lives in the `dev` group.
- `just run [profile]`, `just run_offline`, `just install`.

## Known gaps

- Offline mode needs a `./cached/` directory of JSON fixtures that isn't in the repo.
- Run/task lists are capped at 25 and not paginated.
