# Open WebUI Plugin Maintenance

- Keep the bundled Filter, Pipe, Action, and Event examples compatible with Airpods discovery and import behavior; see [README](README.md).
- `airpods/plugins.py` uses Python's AST to recognize exact top-level `Filter`, `Pipe`, `Action`, and `Event` classes. Pure `Tools` modules are copied but not auto-imported.
- IDs derive from normalized relative paths (`filters/example_filter.py` → `airpods_filters_example_filter`). Preserve canonical IDs and the dotted-ID migration when updating plugins.
- Sync tracks bundled files in `.airpods-open-webui-plugins.json`; pruning must remove only previously managed paths and preserve unrelated user files. Imports affect the SQLite `function` table, not the workspace `tool` table.
- Preserve configured owner resolution and existing valves on updates. `cli.plugin_owner` behavior is defined by `resolve_plugin_owner_user_id`; do not assume every row belongs to `system` or that a dedicated system account is created.
- Never create an Open WebUI account or authenticate with built-in credentials. Check runtime stdout/stderr and import failures without exposing configured secrets. Test discovery, ownership, migration, and SQLite contention through `tests/test_plugins.py` and the startup tests.
- Upstream plugin API details belong in upstream docs. Avoid copying long API/schema references here that can drift independently from airpods.
