# docs/commands/workflows

Manage ComfyUI workflow JSON files and the model files they reference. Use `airpods workflows path` to see provider-specific workspace, workflow, and model directories, or `airpods workflows api` for endpoint information.

```bash
airpods workflows add ./my-workflow.json
airpods workflows list
airpods workflows sync my-workflow.json --dry-run
airpods workflows sync my-workflow.json
```

## Commands

| Command                        | Behavior                                                                                                                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `add [source]`                 | Import a local JSON file, URL, or bundled workflow name; detect a companion TOML mapping. No source lists bundled workflows.               |
| `list` (`ls`)                  | List saved workflows with model/sync information.                                                                                          |
| `sync [workflow]`              | Download missing referenced models; no workflow lists saved workflows.                                                                     |
| `desync <workflow>`            | Remove local models referenced by a workflow; supports `--dry-run` and confirms unless `--yes`. Models may be shared with other workflows. |
| `pull <url> --folder <folder>` | Download one model into the selected model subfolder; optional `--name` and `--subdir`.                                                    |
| `remove <workflow>` (`delete`) | Remove the saved workflow JSON; model files remain.                                                                                        |
| `path`                         | Show workspace/workflows/models paths.                                                                                                     |
| `api`                          | Show ComfyUI API endpoints.                                                                                                                |

`add --sync` downloads models after import; `--overwrite` permits replacing a workflow. `sync` supports `--map`, `--yes`, `--dry-run`, `--overwrite`, and `--interactive/--no-interactive`. Use `--hf-token` or `HF_TOKEN` for gated downloads. Run individual commands with `--help` for timeout/retry options.

## Model Mappings

Save a TOML file beside the workflow with the same stem (`my-workflow.toml` beside `my-workflow.json`):

```toml
[models."model-name.safetensors"]
url = "https://huggingface.co/org/repo/resolve/main/model-name.safetensors"
folder = "checkpoints"
```

Replace the URL and filename with the model required by your workflow. Sync also reads embedded download metadata. Missing URLs/folders can be resolved interactively; inspect `--dry-run` before downloading or deleting models.

The optional bundled-workflow lookup uses `plugins/comfyui/workflows/`; no workflow examples are currently shipped there. See [ComfyUI](../services/comfyui.md) for service setup.
