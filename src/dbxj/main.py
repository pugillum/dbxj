import asyncio
import os
import sys
from argparse import ArgumentParser
from importlib.metadata import version
from typing import Optional
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.notifications import SeverityLevel

from textual.screen import Screen
from textual.widget import Widget
from textual import work
from textual.timer import Timer
from textual.widgets import Footer, Label, Static

from databricks.sdk import WorkspaceClient

from dbxj.auth import AuthError, ReauthScreen, available_profiles, config_path, connect
from dbxj.mock_workspace_client import get_mock_client
from dbxj.body import Body
from dbxj.dialogs import HelpScreen


class Header(Widget):
    def initialise(self, profile: str | None, workspace_id: int, user_name: str | None) -> None:
        self.query_one("#profile", Label).update(f"[b]Profile[/]: {profile or 'default'}")
        self.query_one("#workspace", Label).update(f"[b]Workspace[/]: {workspace_id}")
        self.query_one("#user", Label).update(f"[b]User[/]: {user_name}")

    def compose(self) -> ComposeResult:
        yield Label(id="profile")
        yield Label(id="workspace")
        yield Label(id="user")


class StatusBar(Horizontal):
    """The bottom bar: key hints on the left, a brief status message on the right (like lazygit)."""

    SEVERITY_STYLES = {"information": "green", "warning": "yellow", "error": "red"}
    clear_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        # ctrl+p still opens the palette, it just isn't advertised
        yield Footer(show_command_palette=False)
        yield Static(id="status_message", markup=False)

    def show_message(self, message: str, severity: SeverityLevel, timeout: float) -> None:
        status = self.query_one("#status_message", Static)
        status.update(message)
        status.styles.color = self.SEVERITY_STYLES.get(severity, "white")
        if self.clear_timer is not None:
            self.clear_timer.stop()
        self.clear_timer = self.set_timer(timeout, lambda: status.update(""))


class MainScreen(Screen):
    ws_client: WorkspaceClient
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("q", "app.quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("t", "trigger", "Trigger job", show=False),
        Binding("o", "open", "Open in browser", show=False),
        Binding("tab", "", "Do nothing", show=False),
    ]

    AUTO_FOCUS = "DataTablePlus"

    def __init__(self, offline: bool, profile: str | None) -> None:
        self.offline = offline
        self.profile = profile
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        yield Body(id="body")
        yield StatusBar(id="status_bar")

    def on_mount(self) -> None:
        self.setup_client()

    def action_refresh(self) -> None:
        self.query_one("#body", Body).refresh_view()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_trigger(self) -> None:
        self.query_one("#body", Body).trigger_job()

    def action_open(self) -> None:
        self.query_one("#body", Body).open_in_browser()

    @work(exclusive=True)
    async def setup_client(self) -> None:
        if self.offline:
            self.ws_client = get_mock_client()
            workspace_id = self.ws_client.get_workspace_id()
            user_name = self.ws_client.current_user.me().user_name
        else:
            while True:
                try:
                    self.ws_client, workspace_id, user_name = await asyncio.to_thread(
                        connect, self.profile
                    )
                    break
                except AuthError as e:
                    if not await self.app.push_screen_wait(ReauthScreen(self.profile, str(e))):
                        self.app.exit()
                        return
        self.query_one("#header", Header).initialise(self.profile, workspace_id, user_name)
        self.query_one("#body", Body).initialise(self.ws_client, workspace_id)


class SplashScreen(Screen):
    BINDINGS = [
        ("q", "app.quit", "Quit the app"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(
            r"""
_________/\\\___/\\\_________________________________
 ________\/\\\__\/\\\_________________________________
  ________\/\\\__\/\\\____________________________/\\\_
   ________\/\\\__\/\\\_________/\\\____/\\\______\///__
    ___/\\\\\\\\\__\/\\\\\\\\\__\///\\\/\\\/________/\\\_
     __/\\\////\\\__\/\\\////\\\___\///\\\/_________\/\\\_
      _\/\\\__\/\\\__\/\\\__\/\\\____/\\\/\\\________\/\\\_
       _\//\\\\\\\/\\_\/\\\\\\\\\___/\\\/\///\\\______\/\\\_
        __\///////\//__\/////////___\///____\///__/\\\_\/\\\_
         _________________________________________\//\\\\\\\__
          __________________________________________\///////___
                """,
            id="logo",
        )


class DbxjApp(App):
    CSS_PATH = "main.tcss"

    def __init__(self, offline: bool = False, profile: str | None = None) -> None:
        self.main_screen: Optional[MainScreen] = None
        self.offline = offline
        self.profile = profile

        super().__init__()

    def on_mount(self) -> None:
        self.main_screen = MainScreen(offline=self.offline, profile=self.profile)
        self.push_screen(self.main_screen)
        self.push_screen(SplashScreen())

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
    ) -> None:
        """Show notifications in the bottom bar rather than as Textual's toast overlays."""
        if self.main_screen is None or not self.main_screen.is_mounted:
            super().notify(message, title=title, severity=severity, timeout=timeout)
            return
        if timeout is None:
            timeout = 8 if severity == "error" else 4
        self.main_screen.query_one(StatusBar).show_message(message, severity, timeout)

    # Hides the splash screen and shows the main
    def on_body_jobs_initialised(self, _: Body.JobsInitialised) -> None:
        self.pop_screen()


def parse_args():
    parser = ArgumentParser(prog="dbxj", description="Browse Databricks jobs, runs and task logs")
    parser.add_argument(
        "--offline",
        "--demo",
        help="Run against bundled demo data (no workspace needed)",
        action="store_true",
    )
    parser.add_argument(
        "--profile",
        help=f"Profile from {config_path()} to use",
        default=os.environ.get("DATABRICKS_CONFIG_PROFILE"),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('dbxj')}")

    return parser.parse_args()


def main():
    args = parse_args()

    if args.profile and not args.offline and args.profile not in available_profiles():
        print(f"Profile '{args.profile}' not found in {config_path()}", file=sys.stderr)
        print("Available profiles: " + ", ".join(available_profiles()), file=sys.stderr)
        sys.exit(1)

    app = DbxjApp(offline=args.offline, profile=args.profile)
    app.run()


if __name__ == "__main__":
    main()
