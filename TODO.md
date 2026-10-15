# TODO

Outstanding work only. Supported behavior is documented in [README](README.md) and [docs](docs/goals.md).

## Services and Integrations

- Validate GPU access and persistent paths with real Podman and Docker, including both ComfyUI providers.
- Add runnable ComfyUI workflow examples and tests for bundled HTTP nodes; consider embedding nodes later.
- Add llama.cpp examples for quantized models, context settings, and multiple clients/backends.
- Improve Open WebUI plugin validation, import diagnostics, developer helpers, and valve configuration. Plugin scaffolding/lifecycle commands remain unimplemented.
- Explore an optional [gateway](docs/plans/service-gateway.md); resolve host-network isolation and authentication before implementation.
- Consider optional notebook/file services only after defining their orchestration requirements.

## Model Management

- Implement [Modelfile editing/model creation](docs/plans/models-edit.md).
- Improve search filters and formatting; consider batch pull/removal.

## Reliability and Distribution

- Expand meaningful unit coverage (long-term target above 90%; current enforced minimum is 55%).
- Add real Podman/Docker smoke tests, GPU integration checks where available, and startup benchmarks.
- Expand plugin import/validation coverage, including upstream WebUI schema changes.
- Add optional full-volume backups including model binaries and config migration tools.
- Publish to PyPI; evaluate system packages and an airpods container image.
- Document a complete offline installation/cache workflow; image pre-fetch already exists.

## Future Scope Decisions

Custom networks, service dependency ordering, remote runtimes, and opt-in telemetry need explicit design decisions. A custom web portal is outside the [current goals](docs/goals.md).

Contributors should follow [AGENTS.md](AGENTS.md) for validation, versioning, and commits.
