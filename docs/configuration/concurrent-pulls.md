# docs/configuration/concurrent-pulls

Airpods can now download multiple container images in parallel when running `airpods start` or `airpods start --pre-fetch`. This reduces wait times on first boot and when refreshing large images like ComfyUI.

## Configuration

```toml
[cli]
max_concurrent_pulls = 3  # default range: 1-10
```

- `1` keeps the legacy sequential behavior
- `2-10` downloads several images at once (bounded by network/disk throughput)
- Validation ensures values stay within reasonable limits

## CLI Overrides

Use `--sequential` to force one-at-a-time downloads regardless of config:

```bash
airpods start --sequential
```

The flag also works with `airpods start --pre-fetch`.

## Behavior

- The unified Rich table now tracks each service’s pull progress independently.
- During a full `airpods start`, GPU/volume/network preparation occurs before downloads begin; `airpods start --pre-fetch` skips those steps and only downloads images.
- If one pull fails, the CLI reports the failure but allows other image pulls to finish.

## Tips

- Keep `max_concurrent_pulls` modest (e.g., 3-4) on slower networks to avoid saturating bandwidth.
- Set it to `1` on systems with limited disk IO or when debugging image pull issues.
- Because the value lives under `[cli]`, you can manage it via `airpods config set cli.max_concurrent_pulls <value>`.
