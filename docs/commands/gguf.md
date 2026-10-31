# docs/commands/gguf

Manage shared GGUF files for llama.cpp with `airpods gguf`. No running Ollama service or container runtime is required. In 0.26.1, this replaces `airpods models gguf`; HuggingFace search moves from `airpods models search` to `airpods gguf search`. Ollama imports remain under `airpods models pull`.

### `airpods gguf search <query>`

Search HuggingFace GGUF repositories by name/keywords.

```bash
airpods gguf search llama
airpods gguf search qwen --limit 10
```

**Options:**

- `--limit, -l`: Maximum number of results (default: `5`)

### `airpods gguf list`

List GGUF files stored in the local shared GGUF directory.

```bash
airpods gguf list
airpods gguf ls
```

### `airpods gguf pull <url-or-repo>`

Download a GGUF file to the shared GGUF store. Accepts a direct URL or a HuggingFace spec in the same form as `llama-server -hf`: `owner/repo[:QUANT]` (a leading `hf.co/` or `huggingface.co/` is accepted).

```bash
airpods gguf pull https://example.com/model.gguf
airpods gguf pull https://example.com/model.gguf --name my-model.gguf
airpods gguf pull saidutta69/Qwen3.5-4B-heretic:Q4_K_M
airpods gguf pull bartowski/Llama-3.2-3B-Instruct-GGUF --yes
```

HuggingFace specs:

- The quant tag is matched case-insensitively against filenames as a whole token (`Q4_K` does not match `Q4_K_M`). Without a tag, `Q4_K_M` is used.
- If the default quant is missing or several files match, you are prompted to choose. An explicit tag with no match is an error.
- Split GGUFs (`-00001-of-0000N`) are downloaded as a group.
- If the repo has an `mmproj` file, you are prompted whether to download it (and which one, if several). `--mmproj` / `--no-mmproj` answer in advance; `--yes` (or `cli.auto_confirm`) skips mmproj unless `--mmproj` is given, and fails on ambiguous matches.
- `--hf-token` (or `HF_TOKEN`) supports gated repos. `--name` only applies to a single file.

### `airpods gguf remove <filename>`

Delete a GGUF file from the shared GGUF store immediately, without a confirmation prompt.

```bash
airpods gguf remove my-model.gguf
```

## Storage and Selection

Files live in `<state-root>/volumes/airpods_models/gguf/`, mounted at `/models` in llama.cpp. Downloading a file does not change the active model. See [llama.cpp model selection](../services/llamacpp.md#models-and-arguments) for switching models.
