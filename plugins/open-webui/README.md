# Open WebUI Plugins

Airpods syncs Python plugins from this directory when `airpods start open-webui` runs, including when WebUI is already running. Bundled examples:

- [filters/example_filter.py](filters/example_filter.py): filter hooks and valves.
- [filters/vision_router.py](filters/vision_router.py): vision-model routing.
- [pipes/example_pipeline.py](pipes/example_pipeline.py): pipeline example.
- [actions/example_action.py](actions/example_action.py): action hook.

## Sync and Import

1. Mirror Python files into `<state-root>/volumes/webui_plugins/`, mounted at `/app/backend/data/functions`. Stale Python files are pruned. Edit source plugins, since target-only changes can be replaced or removed.
2. Wait for WebUI's database tables, then attempt import into the SQLite `function` table.
3. Review the functions in WebUI's Admin interface and configure their valves. Imports set active, non-global function rows; import/reload is best effort and failures are reported during startup.

`__init__.py` and filenames starting with `_` are ignored. Discovery recognizes filter, action, and pipeline hooks by source text. Tool-only modules are copied but require WebUI's own tool import flow; airpods does not write the `tool` table. IDs use dotted relative paths, so `filters/example_filter.py` becomes `filters.example_filter`. Upserts update content without resetting existing valves.

## Ownership

`cli.plugin_owner` selects the owner:

- `auto` (default): reuse an existing admin. On an empty user database, attempt to create the built-in `admin@airpods` / `admin` account; startup prints the credentials if creation succeeds. Change that password in Settings if this account is created. Otherwise fall back to `system`.
- `admin`: reuse an existing admin, otherwise use `system`; does not create an account.
- `airpods`: legacy mode; currently falls back to `system` because dedicated-owner creation is disabled.

Set `cli.plugin_owner = "admin"` if WebUI should manage initial account creation itself.

## Troubleshooting

The default database is `<state-root>/volumes/airpods_webui_data/webui.db`, mounted at `/app/backend/data/webui.db`. The session secret is `<state-root>/configs/webui_secret`.

Check startup output for sync/import warnings and `airpods logs open-webui` for WebUI errors. Imports retry SQLite locks but depend on the upstream schema. If automatic import or reload fails, use WebUI's function import interface and restart WebUI if necessary.

To add a plugin, start with the matching bundled example. Changes to installed package files can be replaced on upgrade; keep your source copies separately.
