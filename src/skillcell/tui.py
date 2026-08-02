"""Terminal UI: browse manifests, validate on select, run a Cell's offline loop.

Optional feature — requires the ``tui`` extra (``pip install skillcell[tui]``).
The app takes a manifest directory so it is fully testable headless via
Textual's pilot harness.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from .loop import run_loop
from .manifest import Cell, Chain, ManifestError, load_manifest
from .router import default_router


def _describe(manifest: Cell | Chain) -> str:
    if isinstance(manifest, Cell):
        tools = ", ".join(manifest.tools) or "none"
        return (
            f"kind: Cell\nname: {manifest.name}\nscope: {manifest.scope}\n"
            f"runtime: {manifest.runtime}\nnetwork: {manifest.network}\ntools: {tools}"
        )
    nodes = ", ".join(node.alias for node in manifest.nodes)
    edges = ", ".join(f"{e.source}->{e.target}" for e in manifest.edges) or "none"
    return f"kind: Chain\nname: {manifest.name}\nnodes: {nodes}\nedges: {edges}"


class SkillcellApp(App[None]):
    """Manifest browser: list on the left, validation/run detail on the right."""

    CSS = """
    #manifest-list { width: 40%; }
    #detail { width: 60%; padding: 1; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "run_cell", "Run offline loop"),
    ]

    def __init__(self, manifest_dir: str | Path) -> None:
        super().__init__()
        self._dir = Path(manifest_dir)
        self._selected: Cell | Chain | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(
                *(
                    ListItem(Label(path.name), name=path.name)
                    for path in sorted(self._dir.glob("*.yaml"))
                ),
                id="manifest-list",
            )
            yield Static("select a manifest", id="detail")
        yield Footer()

    def _show(self, text: str) -> None:
        self.query_one("#detail", Static).update(text)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if not name:  # pragma: no cover - list items always carry names
            return
        try:
            self._selected = load_manifest(self._dir / name)
        except (ManifestError, OSError) as exc:
            self._selected = None
            self._show(f"error: {exc}")
            return
        self._show(_describe(self._selected))

    def action_run_cell(self) -> None:
        if not isinstance(self._selected, Cell):
            self._show("run: only Cell manifests are runnable (select a Cell first)")
            return
        result = run_loop(
            goal=self._selected.scope,
            router=default_router,
            backend=None,
            act_mode=False,
            authorized=False,
        )
        stages = "\n".join(f"{s.name:8} {s.status:8} {s.detail}" for s in result.stages)
        self._show(
            f"cell: {self._selected.name}\nroute: {result.route}\n"
            f"executed: {result.executed}\n\n{stages}"
        )


def run_tui(manifest_dir: str | Path) -> None:  # pragma: no cover - interactive entry
    SkillcellApp(manifest_dir).run()
