"""Regression coverage for sizes reliability."""

from __future__ import annotations

from unittest.mock import MagicMock

from airpods.cli.commands import clean
from airpods.services import ServiceSpec


def test_cleanup_uses_numeric_image_size(monkeypatch):
    manager = MagicMock()
    manager.runtime.image_size_bytes.return_value = int(1.5 * 1024**3)
    monkeypatch.setattr(clean, "manager", manager)
    spec = ServiceSpec(
        name="example", pod="example", container="example-0", image="example/image"
    )
    plan = clean._collect_cleanup_targets(specs=[spec], images=True)
    assert plan.total_bytes() == int(1.5 * 1024**3)
    manager.runtime.image_size.assert_not_called()
