# Open WebUI Plugin Maintenance

- Keep the bundled filter/action/pipeline examples compatible with airpods' discovery and import behavior; see [README](README.md).
- `airpods/plugins.py` discovers functions by source markers (`def action`, `class Pipeline`/`def pipe`, `class Filter`/`def inlet`/`def outlet`). Pure `Tools` modules are copied but not auto-imported.
- IDs derive from relative paths with dots (`filters/example_filter.py` → `filters.example_filter`); preserve stable IDs when updating plugins.
- Sync mirrors Python files under the default `webui_plugins` bind mount and prunes stale files. Imports upsert the SQLite `function` table; they do not write the workspace `tool` table.
- Preserve configured owner resolution and existing valves on updates. `cli.plugin_owner` behavior is defined by `resolve_plugin_owner_user_id`; do not assume every row belongs to `system` or that a dedicated system account is created.
- Check runtime stdout/stderr and import failures without exposing configured secrets. Test discovery, ownership, and SQLite contention through `tests/test_plugins.py` and the startup tests.
- Upstream plugin API details belong in upstream docs. Avoid copying long API/schema references here that can drift independently from airpods.
