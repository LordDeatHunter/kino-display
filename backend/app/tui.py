"""The launcher menu shown by `python main.py`.

Two screens: a main menu (Movies / Series / Start) and, behind the first two, a
list of that library's folders you can add to and remove from. Every edit is
written to config.json straight away, so there is no save step to forget.

Esc backs out of a library screen; Esc on the main menu quits without starting
the server.
"""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static

from .config import CONFIG_PATH, MEDIA_KINDS, MediaKind, env_library_dirs
from .setup import config_dirs, current_dirs, load_config, pick_directory, resolve_path, save_dirs

KIND_TITLES: dict[MediaKind, str] = {"movies": "Movies", "series": "Series"}


def highlight_row(listing: ListView, index: int) -> None:
    """Select a row and make sure it is actually drawn as selected.

    Assigning the index it already holds — which is what a fresh list on row 0, or
    a rebuild that lands back on the same row, does — never fires the watcher that
    paints the highlight, so the row is live but looks inert. Clearing it first
    forces the repaint.
    """
    listing.index = None
    listing.index = index


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
        self.heading = title
        self.label = Label(self._markup(hint))
        super().__init__(self.label, id=f"menu-{action}")
        self.action_name = action

    def _markup(self, hint: str) -> str:
        return f"[b]{self.heading}[/b]\n[dim]{hint}[/dim]"

    def set_hint(self, hint: str) -> None:
        self.label.update(self._markup(hint))


class PathItem(ListItem):
    """One configured folder, with a tick box you toggle with Space."""

    def __init__(self, index: int | None, path: Path | None, markup: str) -> None:
        self.label = Label(markup)
        super().__init__(self.label)
        self.path_index = index
        self.path = path
        self.checked = False

    def redraw(self) -> None:
        if self.path is None:
            return
        box = "[b green][x][/]" if self.checked else "[dim][ ][/]"
        missing = "" if self.path.is_dir() else "  [yellow](missing)[/yellow]"
        self.label.update(f"{box} {self.path}{missing}")

    def toggle(self) -> None:
        if self.path is None:
            return
        self.checked = not self.checked
        self.redraw()


class SourceList(ListView):
    """The folder list. Space ticks a row; arrowing past the end leaves the list."""

    BINDINGS = [Binding("space", "toggle_check", "Tick / untick")]

    def action_toggle_check(self) -> None:
        item = self.highlighted_child
        if isinstance(item, PathItem):
            item.toggle()
            self.screen.refresh_note()  # type: ignore[attr-defined]

    def action_cursor_down(self) -> None:
        # At the bottom of the list, carry on down into the buttons rather than
        # stopping dead.
        if self.index is not None and self.index >= len(self.children) - 1:
            self.screen.focus_actions()  # type: ignore[attr-defined]
            return
        super().action_cursor_down()


class ActionButton(Button):
    """A button on the action row, reachable by walking down out of the list."""

    def key_up(self, event: events.Key) -> None:
        event.stop()
        self.screen.focus_list()  # type: ignore[attr-defined]

    def key_left(self, event: events.Key) -> None:
        event.stop()
        self.screen.focus_previous(ActionButton)

    def key_right(self, event: events.Key) -> None:
        event.stop()
        self.screen.focus_next(ActionButton)


class SourcesScreen(Screen[None]):
    """The folders one library scans."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add_source", "Add source"),
        Binding("d", "delete_source", "Remove"),
        Binding("delete", "delete_source", "Remove", show=False),
    ]

    def __init__(self, kind: MediaKind) -> None:
        super().__init__()
        self.kind = kind
        self.paths: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"{KIND_TITLES[self.kind]} sources", classes="heading")
        yield Static("", id="source-note", classes="note")
        yield SourceList(id="sources")
        yield Horizontal(
            ActionButton("＋ Add source", id="add", variant="primary"),
            ActionButton("🗑 Remove selected", id="remove"),
            ActionButton("← Back", id="back"),
            classes="actions",
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_paths()
        self.query_one("#sources", SourceList).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter, or a mouse click, ticks a row the same way Space does."""
        if isinstance(event.item, PathItem):
            event.item.toggle()
            self.refresh_note()

    # ---- focus ----------------------------------------------------------

    def focus_actions(self) -> None:
        """Walking down out of the list lands on the first button."""
        self.query_one("#add", ActionButton).focus()

    def focus_list(self) -> None:
        """Walking up out of the buttons returns to the last row."""
        listing = self.query_one("#sources", SourceList)
        listing.focus()
        if listing.children:
            highlight_row(listing, len(listing.children) - 1)

    # ---- state ----------------------------------------------------------

    def _items(self) -> list[PathItem]:
        return [
            item
            for item in self.query_one("#sources", SourceList).children
            if isinstance(item, PathItem) and item.path_index is not None
        ]

    def ticked(self) -> list[PathItem]:
        return [item for item in self._items() if item.checked]

    def refresh_note(self) -> None:
        note = self.query_one("#source-note", Static)
        ticked = len(self.ticked())
        if ticked:
            note.update(f"[b green]{ticked} ticked[/] [dim]· D removes them[/dim]")
        elif self.paths:
            note.update(
                f"[dim]saved in {CONFIG_PATH.name} · Space ticks a folder, D removes[/dim]"
            )
        elif env_library_dirs(self.kind):
            # Nothing in config.json, but the environment supplies folders anyway;
            # adding one here starts a config.json list that then wins over it.
            note.update(
                f"[dim]none saved — using {self.kind.upper()}_DIRS from the environment[/dim]"
            )
        else:
            note.update("[dim]no folders configured yet[/dim]")

    async def refresh_paths(self, keep: int = 0) -> None:
        """Rebuild the list from config.json.

        The clear and the appends are awaited: they are queued operations, and
        setting the highlight before the new rows have mounted leaves the list
        looking like nothing is selected.
        """
        self.paths = config_dirs(load_config(), self.kind)

        listing = self.query_one("#sources", SourceList)
        await listing.clear()
        if not self.paths:
            await listing.append(
                PathItem(None, None, "[dim]nothing here yet — press [b]A[/b] to add a folder[/dim]")
            )
            highlight_row(listing, 0)
        else:
            for index, path in enumerate(self.paths):
                item = PathItem(index, path, "")
                await listing.append(item)
                item.redraw()
            highlight_row(listing, min(keep, len(self.paths) - 1))
        self.refresh_note()

    def _save(self, paths: list[Path]) -> None:
        save_dirs(load_config(), self.kind, [path.as_posix() for path in paths])

    def action_back(self) -> None:
        self.app.pop_screen()

    async def action_add_source(self) -> None:
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
        await self.refresh_paths(keep=len(self.paths))
        self.notify(f"Added {resolved}")

    async def action_delete_source(self) -> None:
        """Remove every ticked folder, or just the highlighted one if none are."""
        chosen = self.ticked()
        if not chosen:
            item = self.query_one("#sources", SourceList).highlighted_child
            if not isinstance(item, PathItem) or item.path_index is None:
                return
            chosen = [item]

        doomed = {item.path_index for item in chosen}
        first = min(doomed)  # type: ignore[type-var]
        removed = [self.paths[index] for index in sorted(doomed)]  # type: ignore[index]

        self._save([path for position, path in enumerate(self.paths) if position not in doomed])
        await self.refresh_paths(keep=max(0, first - 1))
        if len(removed) == 1:
            self.notify(f"Removed {removed[0]}")
        else:
            self.notify(f"Removed {len(removed)} folders")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            await self.action_add_source()
        elif event.button.id == "remove":
            await self.action_delete_source()
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

    def on_mount(self) -> None:
        self.select_row(0)

    def on_screen_resume(self) -> None:
        """Folder counts can have changed while a library screen was open.

        The rows are updated in place: clearing and re-adding them drops the
        highlight from the selected row, leaving the menu looking like nothing is
        selected at all.
        """
        for kind in MEDIA_KINDS:
            self.query_one(f"#menu-{kind}", MenuItem).set_hint(_summary(kind))
        self.select_row(self.query_one("#menu", ListView).index or 0)

    def select_row(self, index: int) -> None:
        listing = self.query_one("#menu", ListView)
        listing.focus()
        highlight_row(listing, index)

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
    .actions Button:focus { text-style: bold reverse; }
    """

    def on_mount(self) -> None:
        self.push_screen(MainScreen())


def run_launcher() -> bool:
    """Show the menu. True means "start the app", False means "quit"."""
    return bool(LauncherApp().run())
