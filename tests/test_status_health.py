from __future__ import annotations

from airpods.cli.status_view import check_service_health, ping_service
from airpods.services import ServiceSpec


class _Response:
    def __init__(self, status: int):
        self.status = status


class _Connection:
    def __init__(self, status: int):
        self._status = status

    def request(self, method: str, path: str) -> None:  # noqa: ARG002
        return None

    def getresponse(self) -> _Response:
        return _Response(self._status)

    def close(self) -> None:
        return None


def test_check_service_health_uses_expected_status_range(monkeypatch):
    spec = ServiceSpec(
        name="svc",
        pod="svc",
        container="svc-0",
        image="svc:latest",
        health_path="/health",
        health_expected_status=(401, 401),
    )

    monkeypatch.setattr(
        "airpods.cli.status_view.http.client.HTTPConnection",
        lambda host, port, timeout: _Connection(401),  # noqa: ARG005
    )

    assert check_service_health(spec, 8080) is True


def test_ping_service_respects_expected_status_range(monkeypatch):
    spec = ServiceSpec(
        name="svc",
        pod="svc",
        container="svc-0",
        image="svc:latest",
        health_path="/health",
        health_expected_status=(200, 299),
    )

    monkeypatch.setattr(
        "airpods.cli.status_view.http.client.HTTPConnection",
        lambda host, port, timeout: _Connection(503),  # noqa: ARG005
    )

    status = ping_service(spec, 8080)
    assert status.startswith("[warn]503")
