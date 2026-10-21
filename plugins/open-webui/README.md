# Open WebUI Plugins

Airpods syncs bundled Python plugins when `airpods start open-webui` runs, including when Open WebUI is already running. The examples follow Open WebUI's current Function contracts:

- [filters/example_filter.py](filters/example_filter.py): an async Filter with administrator and per-user valves.
- [filters/vision_router.py](filters/vision_router.py): non-blocking image caption routing to an OpenAI-compatible vision endpoint.
- [pipes/example_pipeline.py](pipes/example_pipeline.py): an async Pipe with optional status events.
- [actions/example_action.py](actions/example_action.py): an Action that returns Open WebUI's message-update payload.

Refer to the upstream [Functions](https://docs.openwebui.com/features/extensibility/plugin/functions/), [Pipe](https://docs.openwebui.com/features/extensibility/plugin/functions/pipe/), and [Action](https://docs.openwebui.com/features/extensibility/plugin/functions/action/) documentation for the complete API.

## Sync and Import

1. Bundled Python files are copied to `<state-root>/volumes/webui_plugins/`, mounted at `/app/backend/data/functions`.
2. `.airpods-open-webui-plugins.json` records managed paths and SHA-256 hashes. Changed bundled files are replaced regardless of timestamps. Pruning removes only paths from the previous Airpods manifest; unrelated user files are preserved.
3. Once Open WebUI's database is ready, Airpods discovers exact top-level `Pipe`, `Filter`, `Action`, and `Event` classes with Python's AST and imports only manifest-managed functions.
4. Tool-only modules are copied but are not inserted into Open WebUI's `tool` table. Import those through Open WebUI's own tool workflow.

`__init__.py` and files beginning with `_` are ignored. IDs are lowercase Python identifiers derived from the full relative path and prefixed with `airpods_`. For example, `filters/example_filter.py` becomes `airpods_filters_example_filter`. This avoids the routing ambiguity caused by dotted Pipe IDs.

Older dotted IDs such as `filters.example_filter` are migrated transactionally. The migration updates known function history, user valve, and model references. If both old and new IDs exist, Airpods refuses the migration and reports the conflict instead of choosing or deleting either row.

Imports update the owner, name, type, source, and Airpods metadata. Existing creation time, enabled/global state, valves, and unrelated metadata are preserved. Open WebUI reloads changed function source from its database; Airpods does not sign in or store WebUI credentials for a second reload step.

## Ownership

`cli.plugin_owner` selects the database owner without creating or modifying accounts:

- `auto` (default): reuse an existing admin, otherwise use `system`.
- `admin`: reuse an existing admin, otherwise warn and use `system`.
- `airpods`: retained for configuration compatibility; warns and uses `system`.

Create the first account through Open WebUI itself. Airpods never provisions a default password.

## Troubleshooting

The default database is `<state-root>/volumes/airpods_webui_data/webui.db`, mounted at `/app/backend/data/webui.db`. The persistent session secret is `<state-root>/configs/webui_secret`.

Check startup output for categorized create/update/migrate/unchanged counts, and use `airpods logs open-webui` for service errors. Imports retry transient SQLite locks. An unsupported schema, invalid plugin syntax, or old/new ID collision is reported without deleting user data. If automatic import fails, use Open WebUI's function import interface.

To add a bundled function, start from the matching example and keep a unique relative path. Files edited only in the managed target directory are replaced on the next sync; keep source changes in this directory. Unmanaged files in the target directory are preserved but are not auto-imported by Airpods.
