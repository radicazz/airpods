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

Pull a model from Ollama library or HuggingFace (auto-detected).

The pull command intelligently detects the source:

- **Ollama tags** (no `/`): `llama3.2`, `qwen2.5:7b` → pulls from Ollama library
- **HuggingFace repos** (contains `/`): `bartowski/Llama-3.2-3B-Instruct-GGUF` → pulls from HuggingFace

```bash
# Ollama library - simple tags
airpods models pull llama3.2
airpods models pull qwen2.5:7b
airpods models pull mistral:latest

# HuggingFace repos - auto-detected
airpods models pull bartowski/Llama-3.2-3B-Instruct-GGUF
airpods models pull bartowski/Llama-3.2-3B-Instruct-GGUF \
  --file Llama-3.2-3B-Instruct-Q4_K_M.gguf \
  --name llama3.2-3b-q4
```

**Source selection:** `--source/-s ollama` overrides auto-detection for namespaced Ollama tags; `--source huggingface` (or `hf`) forces HuggingFace.

**Options (for HuggingFace repos):**

- `--file, -f`: Specify GGUF filename (otherwise prompted)
- `--name, -n`: Specify model name in Ollama (otherwise auto-generated)

**Features:**

- Automatic source detection (Ollama vs HuggingFace)
- Real-time progress bar with download speed
- Automatic model size detection
- Interactive file selection for HuggingFace repos with multiple GGUF files

**Browse models:**

- Ollama library: https://ollama.com/library
- HuggingFace GGUF: https://huggingface.co/models?library=gguf

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
- Total size
- Modelfile content
- Parameters
- Prompt template (truncated if long)

**Shell completion:** Tab-completion for model names when Ollama is running.

### `airpods models search <query>`

Search HuggingFace GGUF repositories by name/keywords.

```bash
airpods models search llama
airpods models search qwen --limit 10
```

**Options:**

- `--limit, -l`: Maximum number of results (default: `5`)

### `airpods models gguf list`

List GGUF files stored in the local shared GGUF directory.

```bash
airpods models gguf list
airpods models gguf ls
```

### `airpods models gguf pull <url-or-repo>`

Download a GGUF file to the shared GGUF store. Accepts a direct URL or a HuggingFace spec in the same form as `llama-server -hf`: `owner/repo[:QUANT]` (a leading `hf.co/` or `huggingface.co/` is accepted).

```bash
airpods models gguf pull https://example.com/model.gguf
airpods models gguf pull https://example.com/model.gguf --name my-model.gguf
airpods models gguf pull saidutta69/Qwen3.5-4B-heretic:Q4_K_M
airpods models gguf pull bartowski/Llama-3.2-3B-Instruct-GGUF --yes
```

HuggingFace specs:

- The quant tag is matched case-insensitively against filenames as a whole token (`Q4_K` does not match `Q4_K_M`). Without a tag, `Q4_K_M` is used.
- If the default quant is missing or several files match, you are prompted to choose. An explicit tag with no match is an error.
- Split GGUFs (`-00001-of-0000N`) are downloaded as a group.
- If the repo has an `mmproj` file, you are prompted whether to download it (and which one, if several). `--mmproj` / `--no-mmproj` answer in advance; `--yes` (or `cli.auto_confirm`) skips mmproj unless `--mmproj` is given, and fails on ambiguous matches.
- `--hf-token` (or `HF_TOKEN`) supports gated repos. `--name` only applies to a single file.

### `airpods models gguf remove <filename>`

Delete a GGUF file from the shared GGUF store immediately, without a confirmation prompt.

```bash
airpods models gguf remove my-model.gguf
```

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
airpods models pull bartowski/Llama-3.2-3B-Instruct-GGUF

# Non-interactive
airpods models pull bartowski/Llama-3.2-3B-Instruct-GGUF \
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

- Ollama service must be running for `list`, `pull`, `info`, and `remove` (`airpods start ollama`). HuggingFace search and local `gguf` commands do not require Ollama.
- `huggingface-hub` library (included in dependencies, for HuggingFace model pulls)
- Internet connection for pulling models

## Notes

- Ollama models are stored in `volumes/airpods_ollama_data`; `models gguf` operates on `volumes/airpods_models/gguf` under the state root. See [llama.cpp setup](../services/llamacpp.md).
- Large models may take significant time to download
- GGUF files are downloaded to HuggingFace cache then imported to Ollama
- Model names support Ollama's tag syntax (e.g., `model:tag`)
