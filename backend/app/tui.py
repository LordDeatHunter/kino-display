"""The launcher menu shown by `python main.py`.

Two screens: a main menu (Movies / Series / Start) and, behind the first two, a
list of that library's folders you can add to and remove from. Every edit is
written to config.json straight away, so there is no save step to forget.

Esc backs out of a library screen; Esc on the main menu quits without starting
the server.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static

from .config import CONFIG_PATH, MediaKind, env_library_dirs
from .setup import config_dirs, current_dirs, load_config, pick_directory, resolve_path, save_dirs

KIND_TITLES: dict[MediaKind, str] = {"movies": "Movies", "series": "Series"}


def _summary(kind: MediaKind) -> str:
    """"2 sources" / "1 source (1 missing)" / "no sources yet"."""
    paths, _source = current_dirs(load_config(), kind)
    if not paths:
        return "no sources yet"
    missing = sum(1 for path in paths if not path.is_dir())
    label = f"{len(paths)} source{'' if len(paths) == 1 else 's'}"
    return f"{label} ({missing} missing)" if missing else label


class MenuItem(ListItem):
    def __init__(self, action: str, title: str, hint: str) -> None:
        super().__init__(Label(f"[b]{title}[/b]\n[dim]{hint}[/dim]"))
        self.action_name = action


class PathItem(ListItem):
    def __init__(self, index: int | None, markup: str) -> None:
        super().__init__(Label(markup))
        self.path_index = index


class SourcesScreen(Screen[None]):
    """The folders one library scans."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add_source", "Add source"),
        Binding("d", "delete_source", "Remove selected"),
        Binding("delete", "delete_source", "Remove selected", show=False),
    ]

    def __init__(self, kind: MediaKind) -> None:
        super().__init__()
        self.kind = kind
        self.paths: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"{KIND_TITLES[self.kind]} sources", classes="heading")
        yield Static("", id="source-note", classes="note")
        yield ListView(id="sources")
        yield Horizontal(
            Button("＋ Add source", id="add", variant="primary"),
            Button("🗑 Remove selected", id="remove"),
            Button("← Back", id="back"),
            classes="actions",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_paths()

    def refresh_paths(self, keep: int = 0) -> None:
        config = load_config()
        self.paths = config_dirs(config, self.kind)
        note = self.query_one("#source-note", Static)

        if self.paths:
            note.update(f"[dim]saved in {CONFIG_PATH.name}[/dim]")
        elif env_library_dirs(self.kind):
            # Nothing in config.json, but the environment supplies folders anyway;
            # adding one here starts a config.json list that then wins over it.
            note.update(
                f"[dim]none saved — using {self.kind.upper()}_DIRS from the environment[/dim]"
            )
        else:
            note.update("[dim]no folders configured yet[/dim]")

        listing = self.query_one("#sources", ListView)
        listing.clear()
        if not self.paths:
            listing.append(PathItem(None, "[dim]nothing here yet — press [b]A[/b] to add a folder[/dim]"))
            return

        for index, path in enumerate(self.paths):
            missing = "" if path.is_dir() else "  [yellow](missing)[/yellow]"
            listing.append(PathItem(index, f"{path}{missing}"))
        listing.index = min(keep, len(self.paths) - 1)

    def _save(self, paths: list[Path]) -> None:
        save_dirs(load_config(), self.kind, [path.as_posix() for path in paths])

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_add_source(self) -> None:
        # The picker is a Tk dialog, so the TUI has to let go of the terminal
        # while it is open; Textual redraws itself on the way back.
        with self.app.suspend():
            print(f"\nopening the folder picker for {self.kind}...")
            picked = pick_directory(self.paths[-1] if self.paths else None, self.kind)

        if picked is None:
            self.notify("Nothing selected.", severity="warning")
            return
        resolved = resolve_path(picked.as_posix())
        if resolved is None:
            self.notify("That path could not be read.", severity="error")
            return
        if resolved in self.paths:
            self.notify(f"{resolved} is already in the list.", severity="warning")
            return

        self._save([*self.paths, resolved])
        self.refresh_paths(keep=len(self.paths))
        self.notify(f"Added {resolved}")

    def action_delete_source(self) -> None:
        listing = self.query_one("#sources", ListView)
        item = listing.highlighted_child
        if not isinstance(item, PathItem) or item.path_index is None:
            return

        index = item.path_index
        removed = self.paths[index]
        self._save([path for position, path in enumerate(self.paths) if position != index])
        self.refresh_paths(keep=max(0, index - 1))
        self.notify(f"Removed {removed}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            self.action_add_source()
        elif event.button.id == "remove":
            self.action_delete_source()
        else:
            self.action_back()


class MainScreen(Screen[None]):
    # Enter is the ListView's own binding; only Esc needs handling here.
    BINDINGS = [Binding("escape", "quit_launcher", "Quit without starting")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("movielister", classes="banner")
        yield Static(
            "Point each library at the folders it should scan, then start the app.",
            classes="note",
        )
        yield ListView(
            MenuItem("movies", "Movies", _summary("movies")),
            MenuItem("series", "Series", _summary("series")),
            MenuItem("start", "Start", "launch the web app"),
            id="menu",
        )
        yield Footer()

    def on_screen_resume(self) -> None:
        """Folder counts can have changed while a library screen was open."""
        listing = self.query_one("#menu", ListView)
        keep = listing.index or 0
        listing.clear()
        listing.append(MenuItem("movies", "Movies", _summary("movies")))
        listing.append(MenuItem("series", "Series", _summary("series")))
        listing.append(MenuItem("start", "Start", "launch the web app"))
        listing.index = keep

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, MenuItem):
            return
        if item.action_name == "start":
            self.app.exit(True)
        else:
            self.app.push_screen(SourcesScreen(item.action_name))  # type: ignore[arg-type]

    def action_quit_launcher(self) -> None:
        self.app.exit(False)


class LauncherApp(App[bool]):
    TITLE = "movielister"
    SUB_TITLE = "library setup"

    CSS = """
    Screen { align: center top; }

    .banner {
        width: 100%;
        padding: 1 2 0 2;
        text-style: bold;
        color: $accent;
    }

    .heading {
        width: 100%;
        padding: 1 2 0 2;
        text-style: bold;
    }

    .note { width: 100%; padding: 0 2 1 2; color: $text-muted; }

    ListView {
        width: 100%;
        height: auto;
        max-height: 20;
        margin: 0 2;
        background: $surface;
        border: round $primary-darken-2;
    }

    ListItem { padding: 0 1; }

    .actions { width: 100%; height: auto; padding: 1 2; }
    .actions Button { margin-right: 2; }
    """

    def on_mount(self) -> None:
        self.push_screen(MainScreen())


def run_launcher() -> bool:
    """Show the menu. True means "start the app", False means "quit"."""
    return bool(LauncherApp().run())
