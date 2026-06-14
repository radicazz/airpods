"""Start command implementation for launching Podman containers."""

from __future__ import annotations

from typing import Optional

import typer

from airpods import ui
from airpods import __version__
from airpods.logging import console, status_spinner
from airpods.system import detect_gpu, detect_cuda_compute_capability
from airpods.cuda import select_cuda_version, get_cuda_info_display
from airpods.services import ServiceSpec
from airpods.configuration import get_config
from airpods import gguf, state
from dataclasses import replace

from ..common import (
    COMMAND_CONTEXT,
    ensure_runtime_available,
    is_verbose_mode,
    manager,
    print_network_status,
    print_volume_status,
    print_config_info,
    refresh_cli_context,
    resolve_services,
    get_cli_config,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap

from .. import pull as _pull
import airpods.launch as _launch

ensure_podman_available = ensure_runtime_available


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def start(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        service: Optional[list[str]] = typer.Argument(
            None,
            help="Services to start (default: all).",
            metavar="service",
            shell_complete=service_name_completion,
        ),
        force_cpu: bool = typer.Option(
            False, "--cpu", help="Force CPU even if GPU is present."
        ),
        sequential: bool = typer.Option(
            False,
            "--sequential",
            help="Pull images sequentially (overrides cli.max_concurrent_pulls).",
        ),
        pre_fetch: bool = typer.Option(
            False,
            "--pre-fetch",
            help="Download service images without starting containers.",
        ),
        wait: bool = typer.Option(
            False,
            "--wait",
            help="Wait for HTTP health checks before returning (may take a while for some services).",
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Skip confirmation prompts (auto-confirm service start and downloads).",
        ),
    ) -> None:
        """Start pods for specified services."""
        maybe_show_command_help(ctx, help_)

        # Ensure user config exists
        from airpods.configuration import locate_config_file
        from airpods.state import configs_dir
        from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
        import tomlkit
        from airpods.paths import detect_repo_root

        user_config_path = configs_dir() / "config.toml"
        repo_root = detect_repo_root()

        config_path = locate_config_file()
        if not user_config_path.exists():
            should_create = config_path is None
            if not should_create and repo_root and config_path:
                should_create = config_path.is_relative_to(repo_root)
            if should_create:
                user_config_path.parent.mkdir(parents=True, exist_ok=True)
                document = tomlkit.document()
                document.update(DEFAULT_CONFIG_DICT)
                user_config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
                console.print(f"[ok]Created default config at {user_config_path}[/]")
                refresh_cli_context()
                config_path = user_config_path

        if config_path is None:
            config_path = locate_config_file()

        # Check verbose mode from context
        verbose = is_verbose_mode(ctx)
        print_config_info(config_path, verbose=verbose)

        specs = resolve_services(service)
        ensure_runtime_available()

        # Enable CUDA logging during startup flows
        import airpods.config as config_module

        config_module.ENABLE_COMFY_CUDA_LOG = True

        cli_config = get_cli_config()
        yes = yes or bool(getattr(cli_config, "auto_confirm", False))
        max_concurrent_pulls = 1 if sequential else cli_config.max_concurrent_pulls

        if pre_fetch:
            specs_for_download: list[ServiceSpec] = []
            for spec in specs:
                exists = manager.runtime.image_exists(spec.image)
                if exists is True:
                    continue
                specs_for_download.append(spec)
            if not specs_for_download:
                if verbose:
                    console.print("[ok]All requested images are already present[/]")
                return
            # Check for images that need to be downloaded and confirm with user
            if not yes:
                if not _pull._confirm_image_downloads(specs_for_download):
                    console.print("[warn]Download cancelled by user[/]")
                    raise typer.Exit(code=0)
            _pull._pull_images_with_progress(
                specs_for_download,
                max_concurrent=max_concurrent_pulls,
            )
            return

        if not specs:
            console.print(
                "[warn]No services are enabled for this configuration; nothing to start.[/]"
            )
            return

        # Check what's already running first
        pod_rows = manager.pod_status_rows() or {}
        already_running = []
        needs_start = []

        for spec in specs:
            row = pod_rows.get(spec.pod)
            if row and row.get("Status") == "Running":
                # Verify the container is actually running
                if manager.container_exists(spec):
                    already_running.append(spec)
                else:
                    needs_start.append(spec)
            else:
                needs_start.append(spec)

        # Sync plugins even if services are already running.
        from airpods import plugins  # noqa: F401
        from airpods import custom_nodes as custom_nodes_module

        custom_nodes_list = (
            custom_nodes_module.get_custom_node_specs()
            if any(spec.name == "comfyui" for spec in specs)
            else []
        )
        custom_nodes_keep = custom_nodes_module.custom_nodes_keep_entries(
            custom_nodes_list
        )

        synced_webui, synced_comfyui = _launch._maybe_sync_plugins(
            specs, verbose=verbose, keep_custom_nodes=custom_nodes_keep
        )
        custom_nodes_list, custom_nodes_prepared = _launch._maybe_prepare_custom_nodes(
            specs, nodes=custom_nodes_list, verbose=verbose
        )

        # If everything is already running, still auto-import Open WebUI plugins and exit.
        if not needs_start:
            _launch._maybe_import_webui_plugins(
                specs, cli_config=cli_config, verbose=verbose
            )
            _launch._maybe_install_custom_node_requirements(
                specs, nodes=custom_nodes_list, verbose=verbose
            )
            if synced_comfyui > 0:
                console.print(
                    "[warn]ComfyUI is already running; restart is required to load updated custom nodes.[/]"
                )
            if custom_nodes_prepared > 0:
                console.print(
                    "[warn]ComfyUI is already running; restart is required to load newly installed custom nodes.[/]"
                )

            console.print("[ok]All services already running[/]")
            from airpods.cli.status_view import render_status

            render_status(specs)
            return

        # Report what's already running
        if already_running:
            running_names = ", ".join(spec.name for spec in already_running)
            console.print(f"Already running: [ok]{running_names}[/]")

        # Only process services that need to be started
        specs_to_start = needs_start
        config = get_config()

        # Show GPU status (verbose only)
        if verbose:
            gpu_available, gpu_detail = detect_gpu()
            if gpu_available:
                console.print(f"GPU: [ok]enabled[/] ({gpu_detail})")
            else:
                console.print(f"GPU: [muted]not detected[/] ({gpu_detail})")
            if gpu_available and manager.gpu_device_flag is None:
                console.print(
                    "[warn]GPU passthrough not configured for the current runtime. "
                    "Set up NVIDIA CDI or force CPU.[/]"
                )

            # Show CUDA detection info if ComfyUI is being started
            comfyui_specs = [s for s in specs_to_start if s.name == "comfyui"]
            if comfyui_specs:
                has_gpu_cap, gpu_name_cap, compute_cap = (
                    detect_cuda_compute_capability()
                )
                if has_gpu_cap and compute_cap:
                    selected_cuda = select_cuda_version(compute_cap)
                    cuda_info = get_cuda_info_display(
                        has_gpu_cap, gpu_name_cap, compute_cap, selected_cuda
                    )
                    console.print(f"CUDA: [ok]{cuda_info}[/]")
                else:
                    cuda_info = get_cuda_info_display(
                        has_gpu_cap, gpu_name_cap, compute_cap, "cu126"
                    )
                    console.print(f"CUDA: [muted]{cuda_info}[/]")
        else:
            gpu_available, gpu_detail = detect_gpu()

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs_to_start)
        print_volume_status(volume_results, verbose=verbose)

        for spec in specs_to_start:
            if spec.name == "comfyui":
                _launch._ensure_comfyui_user_dirs(spec)

        # Plugins were already synced above for all requested services.

        # Simple log-based startup process
        service_urls: dict[str, str] = {}
        failed_services = []
        timeout_services = []

        def _effective_spec(spec: ServiceSpec) -> ServiceSpec:
            gpu_passthrough_ready = manager.gpu_device_flag is not None
            use_cpu_image = force_cpu or not gpu_available or not gpu_passthrough_ready
            if (
                spec.name == "llamacpp"
                and use_cpu_image
                and spec.cpu_image
                and spec.cpu_image != spec.image
            ):
                return replace(
                    spec,
                    image=spec.cpu_image,
                    needs_gpu=False,
                    force_cpu=True,
                )
            return spec

        specs_for_download: list[ServiceSpec] = []
        for spec in (_effective_spec(spec) for spec in specs_to_start):
            exists = manager.runtime.image_exists(spec.image)
            if exists is True:
                continue
            specs_for_download.append(spec)

        # Validate llama.cpp model presence before pulling images.
        needs_llamacpp = any(spec.name == "llamacpp" for spec in specs_to_start)
        llamacpp_cfg = config.services.get("llamacpp") if needs_llamacpp else None
        if llamacpp_cfg:
            model_arg = None
            if llamacpp_cfg.command_args:
                model_arg = llamacpp_cfg.command_args.get("model")
            if isinstance(model_arg, str) and model_arg.startswith("/models/"):
                rel = model_arg[len("/models/") :]
                host_models = state.resolve_volume_path("airpods_models/gguf")
                model_path = host_models / rel
                if not model_path.exists():
                    console.print(f"[warn]llamacpp model not found: {model_path}[/]")
                    if llamacpp_cfg.default_model_url:
                        console.print(
                            "[info]Default model is configured (small GGUF for most PCs).[/]"
                        )
                        if yes or ui.confirm_action(
                            "Download the default model now?", default=True
                        ):
                            try:
                                gguf.download_model(
                                    llamacpp_cfg.default_model_url, name=rel
                                )
                                console.print(
                                    f"[ok]Downloaded default model to {model_path}[/]"
                                )
                            except Exception as exc:
                                console.print(
                                    f"[error]Failed to download default model: {exc}[/]"
                                )
                                raise typer.Exit(code=1)
                        else:
                            console.print(
                                "[info]Download a GGUF file into the store, then retry:[/]"
                            )
                            console.print(
                                "[info]  airpods models gguf pull <url> --name "
                                f"{rel}[/]"
                            )
                            raise typer.Exit(code=1)
                    else:
                        console.print(
                            "[info]Download a GGUF file into the store, then retry:[/]"
                        )
                        console.print(
                            f"[info]  airpods models gguf pull <url> --name {rel}[/]"
                        )
                        raise typer.Exit(code=1)

        # Final user confirmation before any image pulls or pod/container
        # launch. This is deliberately placed after *all* checks and
        # validations:
        #   - runtime/dependency checks
        #   - already-running pod+container detection
        #   - plugin/custom-node sync + prepare (best-effort)
        #   - volume ensure + status reporting
        #   - comfyui user dir pre-creation
        #   - GPU/CUDA detection + display
        #   - llama.cpp GGUF model presence validation (incl. its own prompt)
        # The prompt is skipped with --yes (or cli.auto_confirm).
        # We still allow the (more detailed) image-download confirmation to
        # follow when pulls are required; cancelling the start confirm here
        # avoids unnecessary work and secondary prompts.
        if not yes and specs_to_start:
            console.print()
            console.print("[bold]Services to start:[/]")
            for spec in specs_to_start:
                console.print(f"  [accent]{spec.name}[/]")
            console.print()
            if not ui.confirm_action("Proceed to start?", default=True):
                console.print("[warn]Start cancelled by user[/]")
                raise typer.Exit(code=0)

        if specs_for_download:
            # Check for images that need to be downloaded and confirm with user
            if not yes:
                if not _pull._confirm_image_downloads(specs_for_download):
                    console.print("[warn]Download cancelled by user[/]")
                    raise typer.Exit(code=0)

            # Pull images with live progress so long pulls don't feel like a hang.
            _pull._pull_images_with_progress(
                specs_for_download, max_concurrent=max_concurrent_pulls, verbose=verbose
            )
        elif verbose:
            console.print("[info]Images already present; skipping pulls[/]")

        # Delegate the heavy remaining work (launch loop + effective spec + CPU
        # fallback, --wait health polling + summaries, auto-Ollama, final hooks,
        # update hint) to the extracted perform_start. This (together with the
        # earlier extractions) completes the split.
        _launch.perform_start(
            specs_to_start,
            cli_config=cli_config,
            verbose=verbose,
            wait=wait,
            force_cpu=force_cpu,
            yes=yes,
            max_concurrent_pulls=max_concurrent_pulls,
            custom_nodes_list=custom_nodes_list,
            manager=manager,
        )

        # The old duplicated launch/wait/ollama-auto/final-hooks code has been
        # completely removed. All of it now lives (and is the single source of
        # truth) in launch.perform_start (called above). The thin start command
        # only owns the Typer surface, first-run config, pre-flight (llama/gguf,
        # volumes, pull decision), early returns, and top-level UX.

    return {"start": start}
