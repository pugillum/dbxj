from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_SECTIONS = [
    (
        "Global",
        [
            ("r", "Refresh the current view"),
            ("?", "Show / hide this help"),
            ("q", "Quit"),
        ],
    ),
    (
        "Jobs",
        [
            ("/", "Filter jobs by name"),
            ("t", "Trigger the selected job"),
            ("o", "Open the selected job in the browser"),
        ],
    ),
    (
        "Runs / tasks / logs",
        [
            ("o", "Open the selected run or task in the browser"),
        ],
    ),
    (
        "Navigation",
        [
            ("enter", "Drill into the selected row"),
            ("esc", "Back / clear filter"),
            ("j / k", "Down / up"),
            ("d / u", "Page down / up"),
            ("h / l", "Scroll table left / right"),
            ("< / >", "Top / bottom of table"),
            ("g / G", "Top / bottom of logs"),
        ],
    ),
]


def help_text() -> Text:
    width = max(len(key) for _, keys in HELP_SECTIONS for key, _ in keys)
    text = Text()
    for i, (section, keys) in enumerate(HELP_SECTIONS):
        if i:
            text.append("\n\n")
        text.append(section, style="bold")
        for key, description in keys:
            text.append("\n")
            text.append(key.rjust(width), style="bold yellow")
            text.append(f"  {description}")
    return text


class HelpScreen(ModalScreen):
    """lazygit-style keybindings overlay."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("question_mark", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help_dialog") as dialog:
            dialog.border_title = "Keybindings"
            dialog.border_subtitle = "esc close"
            yield Static(help_text())


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Confirm", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, message: str) -> None:
        self.title_text = title
        self.message = message
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_dialog") as dialog:
            dialog.border_title = self.title_text
            dialog.border_subtitle = "y confirm · n cancel"
            yield Static(self.message)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
