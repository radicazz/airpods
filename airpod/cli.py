from __future__ import annotations

import os
import sys
import ssl
import http.client
from typing import List, Optional

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airpod import podman
from airpod.config import (
    SERVICES,
    ServiceSpec,
    get_service,
    list_service_names,
    PROJECT_ROOT,
    VOLUMES_DIR,
    DATA_OLLAMA,
    DATA_OPENWEBUI,
    DATA_COMFYUI,
    DATA_COMFYUI_RUN,
    DATA_SHARED,
    DATA_CADDY,
    CLOUDFLARED_VOLUME,
    CONFIG_DIR,
    COMFYUI_CONFIG,
    ensure_caddyfile,
    generate_self_signed_cert,
    get_comfyui_image,
)
from airpod.logging import console, status_spinner
from airpod import state, tunnel as tunnel_mod
from airpod.system import CheckResult, check_dependency, detect_gpu, detect_cuda_capability, get_resource_stats

app = typer.Typer(
    help="Orchestrate local AI services (Ollama, Open WebUI) with Podman + UV.",
    context_settings={"help_option_names": ["-h", "--help"]},
    rich_markup_mode="rich",
)


def _print_banner() -> None:
    """Print ASCII art banner unless AIRPOD_NO_BANNER is set."""
    if os.environ.get("AIRPOD_NO_BANNER"):
        return
    
    banner = Text()
    banner.append("    _    ___ ____  ____   ___  ____ \n", style="bold cyan")
    banner.append("   / \\  |_ _|  _ \\|  _ \\ / _ \\|  _ \\\n", style="bold cyan")
    banner.append("  / _ \\  | || |_) | |_) | | | | | | |\n", style="bold cyan")
    banner.append(" / ___ \\ | ||  _ <|  __/| |_| | |_| |\n", style="bold cyan")
    banner.append("/_/   \\_\\___|_| \\_\\_|    \\___/|____/ \n", style="bold cyan")
    banner.append("\n Local AI Orchestration with Podman", style="dim")
    
    console.print(banner)
    console.print()


def _resolve_services(names: Optional[List[str]], *, include_optional: bool = True) -> List[ServiceSpec]:
    if not names:
        specs = list(SERVICES.values())
        if not include_optional:
            specs = [spec for spec in specs if not spec.optional]
        return specs
    resolved: List[ServiceSpec] = []
    for name in names:
        spec = get_service(name)
        if not spec:
            raise typer.BadParameter(f"unknown service '{name}'. available: {', '.join(list_service_names())}")
        resolved.append(spec)
    return resolved


def _print_checks(checks: List[CheckResult], gpu_available: bool, gpu_detail: str, cuda_capability: Optional[str] = None) -> None:
    table = Table(title="Environment", show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in checks:
        status = "[ok]ok" if check.ok else "[error]missing"
        table.add_row(check.name, status, check.detail)
    table.add_row("gpu (nvidia)", "[ok]ok" if gpu_available else "[warn]not detected", gpu_detail)
    if cuda_capability:
        table.add_row("cuda capability", "[ok]detected", cuda_capability)
    elif gpu_available:
        table.add_row("cuda capability", "[warn]unknown", "unable to detect")
    console.print(table)


def _ensure_podman_available() -> None:
    check = check_dependency("podman", ["--version"])
    if not check.ok:
        console.print("[error]podman is required; install it and re-run.[/]")
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Show CLI version."""
    from airpod import __version__
    console.print(f"airpod {__version__}")


@app.command()
def init() -> None:
    """Verify tools, create local directories, and pre-pull images."""
    _print_banner()
    
    checks = [
        check_dependency("podman", ["--version"]),
        check_dependency("podman-compose", ["--version"]),
        check_dependency("uv", ["--version"]),
    ]
    gpu_available, gpu_detail = detect_gpu()
    
    # Detect CUDA capability for GPU-aware image selection
    cuda_ok, cuda_cap, cuda_detail = detect_cuda_capability()
    cuda_capability_str = cuda_cap.raw if cuda_ok and cuda_cap else None
    
    _print_checks(checks, gpu_available, gpu_detail, cuda_capability_str)

    if not checks[0].ok:
        console.print("[error]podman is required; install it and re-run init.[/]")
        raise typer.Exit(code=1)

    with status_spinner("Creating local directories"):
        # Create all volume directories (self-contained structure)
        podman.ensure_directory(DATA_OLLAMA)
        podman.ensure_directory(DATA_OPENWEBUI)
        podman.ensure_directory(DATA_COMFYUI)
        podman.ensure_directory(DATA_COMFYUI_RUN)
        podman.ensure_directory(DATA_SHARED)
        podman.ensure_directory(DATA_CADDY)
        podman.ensure_directory(CLOUDFLARED_VOLUME)
        # Create ComfyUI config directory
        podman.ensure_directory(COMFYUI_CONFIG)
        console.print(f"[info]Created: {VOLUMES_DIR}")
    
    # Show ComfyUI image selection based on CUDA capability
    if cuda_capability_str:
        comfyui_image = get_comfyui_image(cuda_capability_str)
        console.print(f"[info]ComfyUI image selected: {comfyui_image} (CUDA {cuda_capability_str})")
    elif gpu_available:
        comfyui_image = get_comfyui_image()
        console.print(f"[info]ComfyUI image selected: {comfyui_image} (CUDA capability unknown)")
    else:
        comfyui_image = get_comfyui_image()
        console.print(f"[info]ComfyUI image selected: {comfyui_image} (no GPU)")
    
    with status_spinner("Generating Caddy configuration"):
        ensure_caddyfile()
        console.print(f"[info]Caddyfile ready at {CONFIG_DIR / 'Caddyfile'}")
    
    with status_spinner("Generating self-signed HTTPS certificate"):
        generate_self_signed_cert()
        console.print(f"[info]Certificate created at {CONFIG_DIR / 'certs' / 'localhost.crt'}")

    with status_spinner("Pulling images"):
        for spec in SERVICES.values():
            # Use dynamic image for ComfyUI based on CUDA capability
            if spec.name == "comfyui":
                image_to_pull = get_comfyui_image(cuda_capability_str)
                podman.pull_image(image_to_pull)
            else:
                podman.pull_image(spec.image)

    # Security: ensure a persistent secret key for Open WebUI sessions.
    with status_spinner("Preparing Open WebUI secret"):
        secret = state.ensure_webui_secret()
    console.print(f"[info]Open WebUI secret stored at {state.config_dir() / 'webui_secret'}[/]")

    console.print(Panel.fit("[ok]init complete. All data is self-contained in this project.[/]", border_style="green"))


@app.command()
def start(
    service: Optional[List[str]] = typer.Argument(None, help="Services to start (default: all)."),
    force_cpu: bool = typer.Option(False, "--cpu", help="Force CPU even if GPU is present."),
    portal: bool = typer.Option(True, "--portal/--no-portal", help="Enable portal mode (path-based routing)."),
    tunnel_enabled: bool = typer.Option(False, "--tunnel/--no-tunnel", help="Attach Cloudflare tunnel (requires tunnel init)."),
) -> None:
    """Start pods for specified services. [dim](alias: up)[/dim]"""
    _print_banner()
    if tunnel_enabled and not portal:
        console.print("[error]Cloudflare tunnel requires portal routing. Re-run without --no-portal.[/]")
        raise typer.Exit(code=1)
    
    specs = _resolve_services(service, include_optional=False)
    _ensure_podman_available()
    gpu_available, gpu_detail = detect_gpu()
    
    # Detect CUDA capability for ComfyUI image selection
    cuda_ok, cuda_cap, cuda_detail = detect_cuda_capability()
    cuda_capability_str = cuda_cap.raw if cuda_ok and cuda_cap else None
    
    if cuda_capability_str:
        console.print(f"[info]GPU: {gpu_detail} (CUDA {cuda_capability_str})[/]")
    else:
        console.print(f"[info]GPU: {'enabled' if gpu_available else 'not detected'} ({gpu_detail})[/]")

    tunnel_config: Optional[tunnel_mod.TunnelConfig] = None
    if tunnel_enabled:
        for svc in ("portal", "caddy", "cloudflared"):
            svc_spec = get_service(svc)
            if svc_spec and svc_spec not in specs:
                specs.append(svc_spec)
        ok, message = tunnel_mod.validate_tunnel_config()
        if not ok:
            console.print(f"[error]{message}[/]")
            raise typer.Exit(code=1)
        tunnel_config = tunnel_mod.load_tunnel_config()
    
    with status_spinner("Ensuring local directories"):
        # Ensure directories exist (idempotent)
        podman.ensure_directory(DATA_OLLAMA)
        podman.ensure_directory(DATA_OPENWEBUI)
        podman.ensure_directory(DATA_COMFYUI)
        podman.ensure_directory(DATA_COMFYUI_RUN)
        podman.ensure_directory(DATA_SHARED)
        podman.ensure_directory(DATA_CADDY)
        podman.ensure_directory(COMFYUI_CONFIG)
        if tunnel_enabled:
            podman.ensure_directory(CLOUDFLARED_VOLUME)
    
    with status_spinner("Ensuring Caddy configuration"):
        ensure_caddyfile(use_portal=portal)
        generate_self_signed_cert()
    
    if tunnel_enabled and tunnel_config:
        with status_spinner("Preparing Cloudflare tunnel files"):
            tunnel_mod.ensure_cloudflared_credentials(tunnel_config)
            tunnel_mod.ensure_cloudflared_config(tunnel_config)

    with status_spinner("Pulling images"):
        for spec in specs:
            # Use dynamic image for ComfyUI based on CUDA capability
            if spec.name == "comfyui":
                image_to_pull = get_comfyui_image(cuda_capability_str)
                podman.pull_image(image_to_pull)
            else:
                podman.pull_image(spec.image)

    # Start infrastructure services first (Portal if enabled, then Caddy)
    if portal:
        portal_spec = get_service("portal")
        if portal_spec and portal_spec in specs:
            with status_spinner(f"Creating pod {portal_spec.pod}"):
                podman.ensure_pod(portal_spec.pod, portal_spec.ports)
            with status_spinner(f"Starting {portal_spec.name} (installing dependencies...)"):
                # Install Flask in the container on first run
                env = dict(portal_spec.env)
                podman.run_container(
                    pod=portal_spec.pod,
                    name=portal_spec.container,
                    image=portal_spec.image,
                    env=env,
                    volumes=portal_spec.volumes,
                    gpu=False,
                    command=["sh", "-c", "pip install --no-cache-dir Flask werkzeug && cd /app && python app.py"],
                )
            console.print("[info]📱 Portal enabled - all services accessible at https://localhost:8443[/]")
    
    caddy_spec = get_service("caddy")
    if caddy_spec and caddy_spec in specs:
        with status_spinner(f"Creating pod {caddy_spec.pod}"):
            podman.ensure_pod(caddy_spec.pod, caddy_spec.ports)
        with status_spinner(f"Starting {caddy_spec.name} (gateway)"):
            podman.run_container(
                pod=caddy_spec.pod,
                name=caddy_spec.container,
                image=caddy_spec.image,
                env=caddy_spec.env,
                volumes=caddy_spec.volumes,
                gpu=False,
                command=caddy_spec.command,
            )
        console.print("[info]🔒 Proxy enabled - all services accessible via HTTPS[/]")

    if tunnel_enabled:
        cloudflared_spec = get_service("cloudflared")
        if cloudflared_spec and cloudflared_spec in specs:
            with status_spinner(f"Creating pod {cloudflared_spec.pod}"):
                podman.ensure_pod(cloudflared_spec.pod, cloudflared_spec.ports)
            with status_spinner("Starting cloudflared tunnel"):
                podman.run_container(
                    pod=cloudflared_spec.pod,
                    name=cloudflared_spec.container,
                    image=cloudflared_spec.image,
                    env=cloudflared_spec.env,
                    volumes=cloudflared_spec.volumes,
                    gpu=False,
                    command=cloudflared_spec.command,
                )
            if tunnel_config and tunnel_config.hostname:
                console.print(f"[info]☁️ Tunnel online → https://{tunnel_config.hostname}[/]")
            else:
                console.print("[warn]Cloudflare tunnel running without hostname mapping[/]")

    # Start application services
    for spec in specs:
        if spec.is_infrastructure:
            continue  # Already started
        
        with status_spinner(f"Creating pod {spec.pod}"):
            podman.ensure_pod(spec.pod, spec.ports)
        with status_spinner(f"Starting {spec.name}"):
            use_gpu = spec.needs_gpu and gpu_available and not force_cpu
            env = dict(spec.env)
            
            # Set service-specific environment variables
            if spec.name == "open-webui":
                env["WEBUI_SECRET_KEY"] = state.ensure_webui_secret()
            
            # Determine image to use (dynamic for ComfyUI)
            image_to_use = spec.image
            use_userns_keep_id = False
            if spec.name == "comfyui":
                image_to_use = get_comfyui_image(cuda_capability_str)
                if cuda_capability_str:
                    console.print(f"[info]Using ComfyUI image for CUDA {cuda_capability_str}[/]")
                # Add UID/GID for mmartial/comfyui-nvidia-docker
                env["WANTED_UID"] = str(os.getuid())
                env["WANTED_GID"] = str(os.getgid())
                # Don't use --userns=keep-id with GPU - CDI passthrough is incompatible
                # The image handles UID/GID remapping internally via WANTED_UID/WANTED_GID
                use_userns_keep_id = not use_gpu
            
            podman.run_container(
                pod=spec.pod,
                name=spec.container,
                image=image_to_use,
                env=env,
                volumes=spec.volumes,
                gpu=use_gpu,
                userns_keep_id=use_userns_keep_id,
            )
    
    # Print success panel with service URLs
    console.print()
    success_lines = ["[bold green]Services Started Successfully[/bold green]", ""]
    
    # Show proxy URL if Caddy is running
    if portal:
        success_lines.append("[cyan]●[/cyan] Portal Gateway (HTTPS)")
        success_lines.append("  [bold]https://localhost:8443/[/bold] - Service portal")
        success_lines.append("  [bold]https://localhost:8443/chat[/bold] - Open WebUI")
        success_lines.append("  [bold]https://localhost:8443/comfy[/bold] - ComfyUI")
        success_lines.append("")
    elif caddy_spec and caddy_spec in specs:
        success_lines.append("[cyan]●[/cyan] Gateway (HTTPS)")
        success_lines.append("  [bold]https://localhost:8443[/bold] - Open WebUI")
        success_lines.append("  [bold]https://localhost:8444[/bold] - ComfyUI")
        success_lines.append("")
    if tunnel_enabled:
        success_lines.append("[cyan]●[/cyan] Cloudflare Tunnel")
        if tunnel_config and tunnel_config.hostname:
            success_lines.append(f"  [bold]https://{tunnel_config.hostname}[/bold] - Remote portal (/chat, /comfy)")
        else:
            success_lines.append("  [warn]No hostname configured. Update config/tunnel.json to expose remotely.[/]")
        success_lines.append("")
    
    for spec in specs:
        if spec.is_infrastructure:
            continue  # Already shown
        success_lines.append(f"[cyan]●[/cyan] {spec.name}")
        if spec.ports:
            host_port = spec.ports[0][0]
            success_lines.append(f"  [dim]Internal: :{host_port}[/dim]")
        success_lines.append("")
    
    success_lines.append("[dim]Run 'airpod status' to check health[/dim]")
    
    console.print(Panel("\n".join(success_lines), border_style="green", padding=(1, 2)))


@app.command()
def stop(
    service: Optional[List[str]] = typer.Argument(None, help="Services to stop (default: all)."),
    remove: bool = typer.Option(False, "--remove", "-r", help="Remove pods after stopping."),
    timeout: int = typer.Option(10, "--timeout", "-t", help="Stop timeout seconds."),
) -> None:
    """Stop pods for specified services. [dim](alias: down)[/dim]"""
    specs = _resolve_services(service)
    for spec in specs:
        if spec.optional and service is None and not podman.pod_exists(spec.pod):
            continue
        if not podman.pod_exists(spec.pod):
            console.print(f"[warn]{spec.pod} not found; skipping[/]")
            continue
        with status_spinner(f"Stopping {spec.pod}"):
            podman.stop_pod(spec.pod, timeout=timeout)
        if remove:
            with status_spinner(f"Removing {spec.pod}"):
                podman.remove_pod(spec.pod)
        console.print(f"[ok]{spec.name} stopped[/]")


@app.command()
def status(service: Optional[List[str]] = typer.Argument(None, help="Services to report (default: all).")) -> None:
    """Show pod status. [dim](alias: ps)[/dim]"""
    specs = _resolve_services(service, include_optional=service is not None)
    pod_rows = {row.get("Name"): row for row in podman.pod_status()}

    # System resources table
    stats = get_resource_stats()
    res_table = Table(title="System Resources", header_style="bold cyan", show_header=True)
    res_table.add_column("Resource")
    res_table.add_column("Usage")
    res_table.add_column("Details")
    
    # CPU
    cpu_usage = f"{stats.cpu_percent:.1f}%"
    cpu_details = f"{stats.cpu_count} cores"
    res_table.add_row("CPU", cpu_usage, cpu_details)
    
    # RAM
    ram_usage = f"{stats.ram_percent:.1f}%"
    ram_details = f"{stats.ram_used_gb:.1f} GB / {stats.ram_total_gb:.1f} GB"
    res_table.add_row("RAM", ram_usage, ram_details)
    
    # GPU
    if stats.gpu_name:
        gpu_usage = f"{stats.gpu_percent:.1f}%" if stats.gpu_percent else "n/a"
        gpu_details = f"{stats.gpu_name} - {stats.gpu_used_mb} MB / {stats.gpu_total_mb} MB" if stats.gpu_used_mb else stats.gpu_name
        res_table.add_row("GPU", gpu_usage, gpu_details)
    else:
        res_table.add_row("GPU", "[dim]not detected[/dim]", "-")
    
    # Proxy status
    caddy_spec = get_service("caddy")
    if caddy_spec:
        caddy_row = pod_rows.get(caddy_spec.pod)
        if caddy_row and caddy_row.get("Status") == "Running":
            proxy_url = "https://localhost:8443"
            proxy_ping = _ping_service(caddy_spec, 8443)
            proxy_status = "[ok]✓ online[/ok]" if proxy_ping == "[ok]ok" else f"[warn]⚠ {proxy_ping}[/warn]"
            res_table.add_row("Proxy", proxy_status, proxy_url)
        else:
            res_table.add_row("Proxy", "[warn]✗ offline[/warn]", "https://localhost:8443")
    tunnel_status = tunnel_mod.get_tunnel_status()
    if tunnel_status.get("configured"):
        status_label = "[ok]✓ online[/ok]" if tunnel_status.get("running") else "[warn]✗ offline[/warn]"
        details = tunnel_status.get("url") or "[dim]hostname pending[/dim]"
        res_table.add_row("Tunnel", status_label, details)
    else:
        res_table.add_row("Tunnel", "[dim]not configured[/dim]", "-")
    
    console.print(res_table)
    console.print()

    # Services table
    table = Table(title="Services", header_style="bold cyan")
    table.add_column("Service")
    table.add_column("Status")
    table.add_column("Endpoint")
    table.add_column("Health")

    for spec in specs:
        row = pod_rows.get(spec.pod)
        if not row:
            table.add_row(spec.name, "[warn]absent", "-", "-")
            continue
        
        status_val = row.get("Status", "?")
        status_display = "[ok]running" if status_val == "Running" else f"[warn]{status_val.lower()}"
        
        # Endpoint display
        if spec.is_infrastructure:
            endpoint = "Gateway :443"
        elif spec.ports:
            host_port = spec.ports[0][0]
            endpoint = f"Internal :{host_port}"
        else:
            endpoint = "-"
        
        # Health check
        host_port = _extract_host_port(spec, podman.pod_inspect(spec.pod).get("InfraConfig", {}).get("PortBindings", {}) if podman.pod_inspect(spec.pod) else {})
        health = _ping_service(spec, host_port) if host_port else "-"
        
        table.add_row(spec.name, status_display, endpoint, health)

    console.print(table)


def _extract_host_port(spec: ServiceSpec, port_bindings) -> Optional[int]:
    # Prefer actual bindings; fallback to configured host port.
    if port_bindings:
        first_binding = next(iter(port_bindings.values()), None)
        if first_binding:
            host_port = (first_binding[0] or {}).get("HostPort")
            if host_port:
                try:
                    return int(host_port)
                except ValueError:
                    return None
    if spec.ports:
        return spec.ports[0][0]
    return None


def _ping_service(spec: ServiceSpec, port: Optional[int]) -> str:
    if not spec.health_path or port is None:
        return "-"
    try:
        conn_cls = http.client.HTTPSConnection if getattr(spec, "health_scheme", "http") == "https" else http.client.HTTPConnection
        conn_kwargs = {"timeout": 2.0}
        if conn_cls is http.client.HTTPSConnection and not getattr(spec, "health_verify_tls", True):
            # Local services commonly use self-signed certs; skip verification when requested.
            conn_kwargs["context"] = ssl._create_unverified_context()
        conn = conn_cls("127.0.0.1", port, **conn_kwargs)
        conn.request("GET", spec.health_path)
        resp = conn.getresponse()
        code = resp.status
        conn.close()
        if 200 <= code < 400:
            return "[ok]ok"
        return f"[warn]{code}"
    except Exception as exc:  # noqa: BLE001
        return f"[warn]{type(exc).__name__}"


@app.command()
def logs(
    service: Optional[List[str]] = typer.Argument(None, help="Services to show logs for (default: all)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs."),
    since: Optional[str] = typer.Option(None, "--since", help="Show logs since RFC3339 timestamp or duration."),
    lines: int = typer.Option(200, "--lines", "-n", help="Number of log lines to show."),
) -> None:
    """Show pod logs."""
    specs = _resolve_services(service)
    if follow and len(specs) > 1:
        console.print("[warn]follow with multiple services will stream sequentially; Ctrl+C to stop.[/]")

    for idx, spec in enumerate(specs):
        if idx > 0:
            console.print()
        console.print(Panel.fit(f"[info]Logs for {spec.name} ({spec.container})[/]", border_style="cyan"))
        code = podman.stream_logs(spec.container, follow=follow, tail=lines, since=since)
        if code != 0:
            console.print(f"[warn]podman logs exited with code {code} for {spec.container}[/]")


@app.command()
def path(
    volumes: bool = typer.Option(False, "--volumes", help="Show volume paths only."),
    config: bool = typer.Option(False, "--config", help="Show config path only."),
) -> None:
    """Show where project data and config are stored."""
    import shutil
    
    def get_dir_size(path) -> str:
        """Get human-readable directory size."""
        if not path.exists():
            return "n/a"
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if total < 1024.0:
                return f"{total:.1f} {unit}"
            total /= 1024.0
        return f"{total:.1f} PB"
    
    # If no specific flag, show all
    show_all = not (volumes or config)
    
    if show_all or not config:
        table = Table(title="Data Volumes (Self-Contained)", header_style="bold cyan")
        table.add_column("Location")
        table.add_column("Path")
        table.add_column("Size")
        table.add_column("Exists")
        
        if show_all:
            table.add_row("Project Root", str(PROJECT_ROOT), "-", "✓")
            table.add_row("Volumes", str(VOLUMES_DIR), get_dir_size(VOLUMES_DIR), "✓" if VOLUMES_DIR.exists() else "✗")
        
        table.add_row("  ├─ Ollama", str(DATA_OLLAMA), get_dir_size(DATA_OLLAMA), "✓" if DATA_OLLAMA.exists() else "✗")
        table.add_row("  ├─ Open WebUI", str(DATA_OPENWEBUI), get_dir_size(DATA_OPENWEBUI), "✓" if DATA_OPENWEBUI.exists() else "✗")
        table.add_row("  ├─ ComfyUI", str(DATA_COMFYUI), get_dir_size(DATA_COMFYUI), "✓" if DATA_COMFYUI.exists() else "✗")
        table.add_row("  └─ Shared", str(DATA_SHARED), get_dir_size(DATA_SHARED), "✓" if DATA_SHARED.exists() else "✗")
        
        console.print(table)
    
    if show_all or config:
        if show_all:
            console.print()
        
        config_table = Table(title="Configuration", header_style="bold cyan")
        config_table.add_column("Location")
        config_table.add_column("Path")
        config_table.add_column("Exists")
        
        config_table.add_row("Config Directory", str(CONFIG_DIR), "✓" if CONFIG_DIR.exists() else "✗")
        secret_file = CONFIG_DIR / "webui_secret"
        config_table.add_row("  └─ WebUI Secret", str(secret_file), "✓" if secret_file.exists() else "✗")
        
        console.print(config_table)
    
    if show_all:
        console.print()
        console.print("[info]💡 Tip: To backup everything, just copy the entire project folder![/]")


# Tunnel command group
tunnel_app = typer.Typer(help="Manage Cloudflare tunnel for remote access.")


@tunnel_app.command("init")
def tunnel_init(
    tunnel_name: str = typer.Option("airpod-tunnel", help="Tunnel name"),
    hostname: Optional[str] = typer.Option(None, help="Custom hostname (e.g., airpod.example.com)"),
) -> None:
    """Initialize a new Cloudflare tunnel."""
    console.print("[info]Initializing Cloudflare tunnel...[/]")
    
    # Check if cloudflared is installed
    installed, msg = tunnel_mod.check_cloudflared_installed()
    if not installed:
        console.print(f"[error]{msg}[/]")
        console.print("\n[warn]Install cloudflared first:[/]")
        console.print("  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb")
        console.print("  sudo dpkg -i cloudflared.deb")
        console.print("\nThen run: cloudflared tunnel login")
        raise typer.Exit(code=1)
    
    console.print(f"[ok]✓ cloudflared found: {msg}[/]")
    
    # Create tunnel
    try:
        with status_spinner(f"Creating tunnel '{tunnel_name}'"):
            config = tunnel_mod.create_tunnel(tunnel_name)
        
        console.print(f"[ok]✓ Tunnel created successfully![/]")
        console.print(f"[info]Tunnel ID: {config.tunnel_id}[/]")
        cred_path = tunnel_mod.ensure_cloudflared_credentials(config)
        console.print(f"[info]Credentials stored at {cred_path}[/]")
        
        if hostname:
            config.hostname = hostname
            tunnel_mod.save_tunnel_config(config)
        
        console.print("\n[bold cyan]Next steps:[/]")
        console.print("1. Add DNS record for your domain:")
        console.print(f"   [dim]cloudflared tunnel route dns {tunnel_name} {hostname or 'your-domain.com'}[/]")
        console.print("2. Start the tunnel:")
        console.print(f"   [dim]airpod start --tunnel[/]")
        
    except RuntimeError as exc:
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(code=1)


@tunnel_app.command("status")
def tunnel_status() -> None:
    """Show tunnel status and info."""
    status = tunnel_mod.get_tunnel_status()
    
    table = Table(title="Tunnel Status", header_style="bold cyan")
    table.add_column("Property")
    table.add_column("Value")
    
    if status["configured"]:
        table.add_row("Tunnel Name", status.get("tunnel_name", "-"))
        table.add_row("Status", "[ok]Running" if status["running"] else "[warn]Stopped")
        table.add_row("URL", status.get("url") or "[dim]not configured[/dim]")
    else:
        table.add_row("Status", "[warn]Not configured")
        table.add_row("Info", "Run 'airpod tunnel init' to create a tunnel")
    
    console.print(table)


@tunnel_app.command("delete")
def tunnel_delete(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete the Cloudflare tunnel."""
    config = tunnel_mod.load_tunnel_config()
    
    if not config.tunnel_id:
        console.print("[warn]No tunnel configured[/]")
        raise typer.Exit(code=0)
    
    if not confirm:
        console.print(f"[warn]This will delete tunnel: {config.tunnel_name}[/]")
        confirm = typer.confirm("Are you sure?")
        if not confirm:
            console.print("[info]Cancelled[/]")
            raise typer.Exit(code=0)
    
    try:
        with status_spinner(f"Deleting tunnel '{config.tunnel_name}'"):
            tunnel_mod.delete_tunnel(config.tunnel_name)
        console.print("[ok]✓ Tunnel deleted successfully[/]")
    except RuntimeError as exc:
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(code=1)


@tunnel_app.command("quick")
def tunnel_quick(
    stop: bool = typer.Option(False, "--stop", help="Stop the quick tunnel"),
) -> None:
    """Start a temporary Cloudflare tunnel (no login required).
    
    This creates a tunnel with a random .trycloudflare.com URL that
    expires when stopped. Perfect for quick testing and sharing.
    """
    _ensure_podman_available()
    
    quick_spec = get_service("cloudflared-quick")
    if not quick_spec:
        console.print("[error]Quick tunnel service not found[/]")
        raise typer.Exit(code=1)
    
    if stop:
        if not podman.pod_exists(quick_spec.pod):
            console.print("[warn]Quick tunnel is not running[/]")
            raise typer.Exit(code=0)
        
        with status_spinner("Stopping quick tunnel"):
            podman.stop_pod(quick_spec.pod, timeout=10)
            podman.remove_pod(quick_spec.pod)
        
        console.print("[ok]✓ Quick tunnel stopped[/]")
        return
    
    # Check if portal/caddy are running
    portal_spec = get_service("portal")
    caddy_spec = get_service("caddy")
    
    if not podman.pod_exists(caddy_spec.pod if caddy_spec else ""):
        console.print("[error]Caddy proxy must be running first[/]")
        console.print("[info]Start services with: airpod start --portal[/]")
        raise typer.Exit(code=1)
    
    # Check if already running
    if podman.pod_exists(quick_spec.pod):
        console.print("[warn]Quick tunnel is already running[/]")
        temp_url = tunnel_mod.get_temp_tunnel_url()
        if temp_url:
            console.print(f"[ok]URL: {temp_url}[/]")
        else:
            console.print("[info]Run 'airpod logs cloudflared-quick' to see the URL[/]")
        raise typer.Exit(code=0)
    
    console.print("[info]Starting temporary Cloudflare tunnel...[/]")
    console.print("[dim]No login or DNS setup required - just wait for your URL![/]")
    
    with status_spinner("Pulling cloudflared image"):
        podman.pull_image(quick_spec.image)
    
    with status_spinner(f"Creating pod {quick_spec.pod}"):
        podman.ensure_pod(quick_spec.pod, quick_spec.ports)
    
    with status_spinner("Starting tunnel (this may take 10-15 seconds)"):
        podman.run_container(
            pod=quick_spec.pod,
            name=quick_spec.container,
            image=quick_spec.image,
            env=quick_spec.env,
            volumes=quick_spec.volumes,
            gpu=False,
            command=quick_spec.command,
        )
    
    # Wait a moment for the tunnel to establish
    import time
    console.print("[info]Waiting for tunnel to establish...", style="dim")
    
    max_attempts = 20
    for attempt in range(max_attempts):
        time.sleep(1)
        temp_url = tunnel_mod.get_temp_tunnel_url()
        if temp_url:
            console.print()
            console.print(Panel.fit(
                f"[bold green]✓ Quick Tunnel Active![/bold green]\n\n"
                f"[cyan]Public URL:[/cyan] [bold]{temp_url}[/bold]\n\n"
                f"[dim]• Share this URL to access your services remotely\n"
                f"• Tunnel expires when stopped (airpod tunnel quick --stop)\n"
                f"• All services available: /chat, /comfy, etc.[/dim]",
                border_style="green",
                padding=(1, 2)
            ))
            return
    
    console.print("[warn]Tunnel started but URL not detected yet[/]")
    console.print("[info]Run 'airpod logs cloudflared-quick' to see the URL[/]")


app.add_typer(tunnel_app, name="tunnel")


# Command aliases (hidden from help, shown inline with main commands)
@app.command(name="up", hidden=True)
def up(
    service: Optional[List[str]] = typer.Argument(None, help="Services to start (default: all)."),
    force_cpu: bool = typer.Option(False, "--cpu", help="Force CPU even if GPU is present."),
    portal: bool = typer.Option(True, "--portal/--no-portal", help="Enable portal mode (path-based routing)."),
    tunnel_enabled: bool = typer.Option(False, "--tunnel/--no-tunnel", help="Attach Cloudflare tunnel (requires tunnel init)."),
) -> None:
    start(service, force_cpu, portal, tunnel_enabled)


@app.command(name="down", hidden=True)
def down(
    service: Optional[List[str]] = typer.Argument(None, help="Services to stop (default: all)."),
    remove: bool = typer.Option(False, "--remove", "-r", help="Remove pods after stopping."),
    timeout: int = typer.Option(10, "--timeout", "-t", help="Stop timeout seconds."),
) -> None:
    stop(service, remove, timeout)


@app.command(name="ps", hidden=True)
def ps(service: Optional[List[str]] = typer.Argument(None, help="Services to report (default: all).")) -> None:
    status(service)


def main() -> None:
    try:
        app()
    except podman.PodmanError as exc:
        console.print(f"[error]{exc}[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
