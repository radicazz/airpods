"""Regression coverage for bootstrap reliability."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from airpods.cli import app


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["--version"],
        ["start", "--help"],
        ["config", "--help"],
        ["models", "pull", "--help"],
    ],
)
def test_bootstrap_without_runtime_or_configuration(args, tmp_path):
    env = dict(os.environ, AIRPODS_CONFIG=str(tmp_path / "missing.toml"))
    code = """
import json, sys
from unittest.mock import patch
with patch('shutil.which', return_value=None):
    from airpods.cli import app
    from typer.testing import CliRunner
    result = CliRunner().invoke(app, json.loads(sys.argv[1]))
    print(result.stdout)
    sys.exit(result.exit_code)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(args)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (tmp_path / "missing.toml").exists()


def test_config_init_repairs_missing_explicit_path(runner, tmp_path, monkeypatch):
    path = tmp_path / "custom" / "broken.toml"
    monkeypatch.setenv("AIRPODS_CONFIG", str(path))
    from airpods.configuration.loader import locate_config_file

    locate_config_file.cache_clear()
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0, result.stdout
    assert path.exists()


def test_config_validate_reports_error_without_traceback(runner, tmp_path, monkeypatch):
    path = tmp_path / "broken.toml"
    path.write_text("[broken")
    monkeypatch.setenv("AIRPODS_CONFIG", str(path))
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 1
    assert "Invalid TOML" in result.stdout
    assert "Traceback" not in result.stdout
