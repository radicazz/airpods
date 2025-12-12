# docs/commands/models

The `models` command provides comprehensive Ollama model management capabilities, allowing you to pull models from both the Ollama library and HuggingFace, list installed models, view model details, and remove models.

## Commands

### `airpods models list`

List all installed Ollama models with size, modification time, and model family information.

```bash
airpods models list
# or
airpods model list
airpods models ls
```

**Output example:**
```
┌──────────────┬──────────┬──────────┬────────────────┐
│ Model        │ Size     │ Modified │ Family         │
├──────────────┼──────────┼──────────┼────────────────┤
│ llama3.2     │ 2.3 GB   │ 2 days   │ llama          │
│ qwen2.5:7b   │ 4.7 GB   │ 1 week   │ qwen2          │
└──────────────┴──────────┴──────────┴────────────────┘

Total storage: 7.0 GB (2 models)
```

### `airpods models pull <model>`

Pull a model from the Ollama official library.

```bash
# Pull latest version
airpods models pull llama3.2

# Pull specific tag
airpods models pull qwen2.5:7b
airpods models pull mistral:latest
```

**Features:**
- Real-time progress bar with download speed
- Automatic model size detection
- Supports all Ollama library models with tag syntax

### `airpods models pull-hf <repo>`

Pull a GGUF model from HuggingFace and import it into Ollama.

```bash
# Interactive mode (prompts for file selection and name)
airpods models pull-hf bartowski/Llama-3.2-3B-Instruct-GGUF

# With options
airpods models pull-hf bartowski/Llama-3.2-3B-Instruct-GGUF \
  --file Llama-3.2-3B-Instruct-Q4_K_M.gguf \
  --name llama3.2-3b-q4
```

**Options:**
- `--file, -f`: Specify GGUF filename (otherwise prompted)
- `--name, -n`: Specify model name in Ollama (otherwise auto-generated with confirmation)

**Interactive prompts:**
1. Lists all available GGUF files in the repository with sizes
2. Prompts for file selection if multiple files available
3. Suggests an auto-generated model name based on repo and file
4. Allows accepting suggested name or entering custom name

### `airpods models remove <model>`

Remove an installed model from Ollama.

```bash
# With confirmation prompt
airpods models remove llama3.2

# Skip confirmation
airpods models remove llama3.2 --force
```

**Options:**
- `--force, -f`: Skip confirmation prompt

**Shell completion:** Tab-completion for model names when Ollama is running.

### `airpods models info <model>`

Show detailed information about an installed model.

```bash
airpods models info llama3.2
```

**Output includes:**
- Model name and license
- Model family and parameter count
- Quantization level
-  Total size
- Modelfile content
- Parameters
- Prompt template (truncated if long)

**Shell completion:** Tab-completion for model names when Ollama is running.

## Auto-Pull on Startup

Configure models to be automatically pulled when Ollama starts:

**config.toml:**
```toml
[services.ollama]
enabled = true
auto_pull_models = ["llama3.2", "qwen2.5:7b"]
```

Models are only pulled if not already installed, so this is safe to run repeatedly.

## Examples

**Pull and test a model:**
```bash
airpods models pull llama3.2
airpods models info llama3.2
```

**Import a quantized model from HuggingFace:**
```bash
# Interactive - will prompt for file selection and name
airpods models pull-hf bartowski/Llama-3.2-3B-Instruct-GGUF

# Non-interactive
airpods models pull-hf bartowski/Llama-3.2-3B-Instruct-GGUF \
  -f Llama-3.2-3B-Instruct-Q4_K_M.gguf \
  -n my-llama-3b
```

**Clean up old models:**
```bash
# List models to see what's installed
airpods models list

# Remove unused models
airpods models remove old-model-name --force
```

## Aliases

The following command aliases are available:
- `model` → `models` (singular form)
- `ls` → `list` (short form)
- `rm` → `remove` (short form)

## Requirements

- Ollama service must be running (`airpods start ollama`)
- For pull-hf: `huggingface-hub` library (included in dependencies)
- Internet connection for pulling models

## Notes

- Models are stored in the Ollama data volume (`airpods_ollama_data`)
- Large models may take significant time to download
- GGUF files are downloaded to HuggingFace cache then imported to Ollama
- Model names support Ollama's tag syntax (e.g., `model:tag`)
