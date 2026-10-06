"""Run Prettier with the TOML plugin installed in its pre-commit environment."""

import json
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    executable = shutil.which("prettier")
    if executable is None:
        sys.exit("Prettier is unavailable; run this through pre-commit.")
    modules = Path(executable).resolve().parents[2]
    plugin = modules / "prettier-plugin-toml"
    metadata = json.loads((plugin / "package.json").read_text())
    entrypoint = plugin / metadata.get("module", metadata["main"])
    return subprocess.call([executable, "--plugin", str(entrypoint), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
