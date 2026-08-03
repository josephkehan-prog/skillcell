"""TUI tests via Textual's pilot harness. The app is constructed against a
manifest directory, so tests run headless on temp dirs and the examples/."""

from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import ListView, Static  # noqa: E402

from skillcell.tui import SkillcellApp  # noqa: E402

EXAMPLES = Path(__file__).parent.parent / "examples"


async def test_app_lists_manifests_from_directory():
    app = SkillcellApp(manifest_dir=EXAMPLES)
    async with app.run_test() as pilot:
        listing = pilot.app.query_one("#manifest-list", ListView)
        names = {item.name for item in listing.children}
        assert names == {
            "wordsmith.yaml",
            "cell.yaml",
            "chain.yaml",
            "refactor-audit-chain.yaml",
        }


async def test_selecting_manifest_shows_validation_in_detail():
    app = SkillcellApp(manifest_dir=EXAMPLES)
    async with app.run_test() as pilot:
        listing = pilot.app.query_one("#manifest-list", ListView)
        idx = [item.name for item in listing.children].index("cell.yaml")
        listing.index = idx
        await pilot.press("enter")
        detail = pilot.app.query_one("#detail", Static)
        text = str(detail.content)
        assert "Cell" in text
        assert "firmware-triage" in text


async def test_invalid_manifest_shows_error_in_detail(tmp_path):
    (tmp_path / "bad.yaml").write_text("kind: Widget\nmetadata: {name: x}\nspec: {}\n")
    app = SkillcellApp(manifest_dir=tmp_path)
    async with app.run_test() as pilot:
        listing = pilot.app.query_one("#manifest-list", ListView)
        listing.index = 0
        await pilot.press("enter")
        detail = pilot.app.query_one("#detail", Static)
        assert "unexpected kind" in str(detail.content)


async def test_run_key_executes_offline_loop_on_cell():
    app = SkillcellApp(manifest_dir=EXAMPLES)
    async with app.run_test() as pilot:
        listing = pilot.app.query_one("#manifest-list", ListView)
        idx = [item.name for item in listing.children].index("cell.yaml")
        listing.index = idx
        await pilot.press("enter")
        await pilot.press("r")
        detail = pilot.app.query_one("#detail", Static)
        text = str(detail.content)
        # offline loop runs all stages; act is skipped without a backend
        assert "align" in text
        assert "skipped" in text


async def test_run_key_on_chain_reports_not_runnable():
    app = SkillcellApp(manifest_dir=EXAMPLES)
    async with app.run_test() as pilot:
        listing = pilot.app.query_one("#manifest-list", ListView)
        idx = [item.name for item in listing.children].index("chain.yaml")
        listing.index = idx
        await pilot.press("enter")
        await pilot.press("r")
        detail = pilot.app.query_one("#detail", Static)
        assert "only Cell manifests" in str(detail.content)


def test_cli_has_tui_subcommand():
    from skillcell.cli import build_parser

    ns = build_parser().parse_args(["tui"])
    assert ns.command == "tui"
