"""Init command for initial setup, volume creation, and image pulling."""

from __future__ import annotations

import tomlkit
import typer
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from airpods import state, ui
from airpods.configuration import locate_config_file
from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
from airpods.logging import console, status_spinner

from ..common import COMMAND_CONTEXT, manager, print_network_status, print_volume_status
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def init(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Verify tools, ensure resources, and report whether anything new was created."""
        maybe_show_command_help(ctx, help_)

        # Create default config file if user doesn't have one in their home directory
        from airpods.state import configs_dir
        from airpods.paths import detect_repo_root

        user_config_path = configs_dir() / "config.toml"
        repo_root = detect_repo_root()

        # Only create user config if it doesn't exist and we're not using a user-set config
        if not user_config_path.exists():
            current_config = locate_config_file()
            # Create if no config exists, or if only repo config exists
            should_create = current_config is None or (
                repo_root and current_config.is_relative_to(repo_root)
            )
            if should_create:
                user_config_path.parent.mkdir(parents=True, exist_ok=True)
                document = tomlkit.document()
                document.update(DEFAULT_CONFIG_DICT)
                user_config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
                console.print(f"[ok]Created default config at {user_config_path}[/]")

        report = manager.report_environment()
        ui.show_environment(report)

        if report.missing:
            console.print(
                f"[error]The following dependencies are required: {', '.join(report.missing)}. Install them and re-run init.[/]"
            )
            raise typer.Exit(code=1)

        with status_spinner("Ensuring network"):
            network_created = manager.ensure_network()
        print_network_status(network_created, manager.network_name)

        specs = manager.resolve(None)

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs)
        print_volume_status(volume_results)

        image_states: dict[str, str] = {spec.name: "pending" for spec in specs}
        image_sizes: dict[str, str] = {}

        def _make_table() -> Table:
            """Create the live-updating image pull table."""
            table = ui.themed_table(
                title="[info]Pulling Images",
            )
            table.add_column("Service", style="cyan")
            table.add_column("Image", style="dim")
            table.add_column("Size", style="dim", justify="right")
            table.add_column("Status", style="")

            for spec in specs:
                state_val = image_states[spec.name]
                size = image_sizes.get(spec.name, "")
                if state_val == "pending":
                    table.add_row(spec.name, spec.image, size, "[dim]Waiting...")
                elif state_val == "pulling":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, size, spinner)
                elif state_val == "done":
                    table.add_row(spec.name, spec.image, size, "[ok]✓ Ready")

            return table

        with Live(_make_table(), refresh_per_second=4, console=console, transient=True) as live:

            def _image_progress(phase, index, _total_count, spec):
                if phase == "start":
                    image_states[spec.name] = "pulling"
                else:
                    image_states[spec.name] = "done"
                live.update(_make_table())

            manager.pull_images(specs, progress_callback=_image_progress)

            # Get image sizes after all pulls complete
            for spec in specs:
                size = manager.runtime.image_size(spec.image)
                if size:
                    image_sizes[spec.name] = size
            live.update(_make_table())

        # Show clean completion summary for image pulls
        if specs:
            console.print(f"[ok]✓ Pulled {len(specs)} image{'s' if len(specs) != 1 else ''}[/]")

        with status_spinner("Preparing Open WebUI secret"):
            secret = state.ensure_webui_secret()
        console.print(
            f"[info]Open WebUI secret stored at {state.webui_secret_path()}[/]"
        )

        ui.success_panel("init complete. pods are ready to start.")

    return {"init": init}
