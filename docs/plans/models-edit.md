# docs/plans/models-edit

Status: proposed; `models edit`, `models create`, and `models tune` are not implemented.

## Purpose

Allow editing an Ollama Modelfile through `$EDITOR` and creating a model variant through Ollama. Keep the CLI focused on managing the existing runtime.

## Proposed Behavior

- `airpods models edit <model>` would load its Modelfile, open an editor, validate the result, and ask for a destination name.
- Replacing an existing model would require explicit confirmation and a recoverable copy of its previous definition.
- Read/show and parameter-level editing could follow if the basic flow proves useful; the nested command syntax is undecided.

## Implementation Work

Reuse the configuration editor conventions and Ollama model information helpers. Define creation/error handling in `airpods/ollama.py`, then test cancelled edits, invalid definitions, creation failures, and replacement behavior. Existing supported commands remain documented in [models](../commands/models.md).
