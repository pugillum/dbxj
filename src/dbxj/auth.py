import os
import subprocess
from configparser import ConfigParser
from pathlib import Path

from databricks.sdk import WorkspaceClient
from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class AuthError(Exception):
    pass


def config_path() -> Path:
    return Path(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")).expanduser()


def available_profiles() -> list[str]:
    parser = ConfigParser()
    parser.read(config_path())
    # ConfigParser treats DEFAULT specially so it doesn't appear in sections()
    profiles = ["DEFAULT"] if parser.defaults() else []
    return profiles + [s for s in parser.sections() if s != "__settings__"]


def connect(profile: str | None) -> tuple[WorkspaceClient, int, str]:
    """Create a client and make API calls to confirm the auth is valid."""
    try:
        ws_client = WorkspaceClient(profile=profile)
        user_name = ws_client.current_user.me().user_name or "Unknown"
        workspace_id = ws_client.get_workspace_id()
    except Exception as e:
        raise AuthError(str(e)) from e
    return ws_client, workspace_id, user_name


class ReauthScreen(ModalScreen[bool]):
    """Runs `databricks auth login`, which opens the browser and waits for the login."""

    BINDINGS = [
        Binding("enter", "retry", "Retry", show=False),
        Binding("r", "retry", "Retry", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("escape", "quit", "Quit", show=False),
    ]

    process: subprocess.Popen | None = None
    waiting = False
    cancelled = False

    def __init__(self, profile: str | None, error: str) -> None:
        self.profile = profile
        self.error = error
        super().__init__()

    def compose(self) -> ComposeResult:
        profile = f"'{self.profile}'" if self.profile else "default profile"
        with Vertical(id="reauth_dialog") as dialog:
            dialog.border_title = f"Login expired: {profile}"
            yield Static(self.error, id="reauth_error", markup=False)
            yield Static(id="reauth_status")

    def on_mount(self) -> None:
        self.action_retry()

    def set_waiting(self, waiting: bool) -> None:
        self.waiting = waiting
        dialog = self.query_one("#reauth_dialog")
        if waiting:
            self.query_one("#reauth_status", Static).update(
                "Opening browser to log in... waiting for login to complete"
            )
            dialog.border_subtitle = "q quit"
        else:
            dialog.border_subtitle = "enter retry · q quit"

    def action_retry(self) -> None:
        if not self.waiting:
            self.set_waiting(True)
            self.login()

    def action_quit(self) -> None:
        self.cancelled = True
        if self.process is not None:
            self.process.terminate()
        self.dismiss(False)

    @work(exclusive=True, thread=True)
    def login(self) -> None:
        command = ["databricks", "auth", "login"]
        if self.profile:
            command += ["--profile", self.profile]

        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = self.process.communicate()
            returncode = self.process.returncode
        except FileNotFoundError:
            self.app.call_from_thread(
                self.login_failed,
                "Databricks CLI not found - install it and make sure it's on PATH",
            )
            return
        finally:
            self.process = None

        if self.cancelled:
            return
        if returncode == 0:
            self.app.call_from_thread(self.dismiss, True)
        else:
            message = stderr.strip() or stdout.strip() or "Login failed"
            if not self.profile:
                message += "\nTry launching with --profile <name>"
            self.app.call_from_thread(self.login_failed, message)

    def login_failed(self, message: str) -> None:
        self.set_waiting(False)
        self.query_one("#reauth_status", Static).update(f"[red]{escape(message)}[/]")
