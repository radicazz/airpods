# docs/plans/models-edit

## Overview

Future interface for editing Ollama model configurations, including Modelfiles, chat templates, and parameters. Deferred for later implementation.

## Proposed Command Structure

### Primary Command
```bash
airpods models edit <model> [subcommand]
```

### Subcommands

**Base edit** (`airpods models edit <model>`)
- Opens Modelfile in `$EDITOR` for full editing
- Prompts for new model name after save (creates variant or replaces original)
- Mirrors `airpods config edit` pattern

**show** (`airpods models edit <model> show`)
- Display Modelfile with syntax highlighting
- Optional `--format` flag (modelfile/json)

**get** (`airpods models edit <model> get <key>`)
- Retrieve specific Modelfile directive
- Dot notation: `parameter.temperature`, `template`, `system`
- Example: `airpods models edit llama3.2 get parameter.temperature`

**set** (`airpods models edit <model> set <key> <value>`)
- Update specific Modelfile directive
- Auto-prompts for new model variant name
- Example: `airpods models edit llama3.2 set parameter.temperature 0.7`

**template** (`airpods models edit <model> template`)
- Interactive template editor
- Offers presets (ChatML, Llama2, Alpaca) or custom editing

**validate** (`airpods models edit <model> validate`)
- Syntax and compatibility checking before model creation

## Design Considerations

1. **Immutability**: Ollama models are immutable; edits create new variants or replace with confirmation
2. **Template library**: Consider built-in common chat template presets
3. **Quick tuning**: Potential shortcut command for common tweaks (`airpods models tune <model> --temperature 0.7`)
4. **Backup strategy**: Auto-backup before in-place replacements

## Integration Notes

- Follows existing `config` command patterns for consistency
- Leverages Ollama API for model creation from Modelfile
- Should integrate with existing `models info` display
- May require helper utilities in `airpods/ollama.py` for Modelfile parsing/generation

## Alignment with Goals

Per `docs/goals.md`:
- Remains focused on orchestration, not replacing Ollama's native capabilities
- Provides clear, safe-by-default commands
- Uses configuration patterns established in airpods CLI
