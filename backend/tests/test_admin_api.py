"""The operator API's access rules (no database needed)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import deps
from src.api.admin import mount_admin
from src.api.errors import install_error_handling
from src.config import override_settings
from src.main import app as main_app

TOKEN = "correct-horse-battery"


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handling(app)
    mount_admin(app)
    return app


@pytest.fixture
def enabled():
    from pydantic import SecretStr

    with override_settings(GRAPHSENSE_ADMIN_TOKEN=SecretStr(TOKEN)):
        assert any(p.startswith("/api/admin") for p in make_app().openapi()["paths"])
        yield TestClient(make_app())


def test_without_a_token_the_admin_routes_do_not_exist():
    with override_settings(GRAPHSENSE_ADMIN_TOKEN=None):
        app = make_app()
        assert not any(p.startswith("/api/admin") for p in app.openapi()["paths"])
        client = TestClient(app)
        assert client.post("/api/admin/datasets/o2c/ingest", json={}).status_code == 404
        assert client.get("/api/admin/runs", headers={"Authorization": "Bearer anything"}).status_code == 404


def test_the_shipped_application_has_no_admin_routes_by_default():
    assert not any(p.startswith("/api/admin") for p in main_app.openapi()["paths"])


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": "Bearer "},
    {"Authorization": TOKEN},  # no scheme
    {"Authorization": f"Basic {TOKEN}"},
    {"Authorization": f"Bearer {TOKEN}x"},
    {"Authorization": f"Bearer {TOKEN[:-1]}"},
])
def test_missing_or_wrong_tokens_are_401(enabled, headers):
    for method, path in (("get", "/api/admin/runs"), ("post", "/api/admin/datasets/o2c/ingest"),
                         ("post", "/api/admin/datasets/o2c/rollback")):
        res = getattr(enabled, method)(path, headers=headers)
        assert res.status_code == 401, path
        assert res.json()["code"] == "unauthorized" and res.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in res.text


def test_the_comparison_is_constant_time(enabled, monkeypatch):
    calls = []
    real = deps.secrets.compare_digest
    monkeypatch.setattr(deps.secrets, "compare_digest", lambda a, b: calls.append((len(a), len(b))) or real(a, b))
    enabled.get("/api/admin/runs", headers={"Authorization": "Bearer short"})
    enabled.get("/api/admin/runs", headers={"Authorization": "Bearer " + "x" * 500})
    # always compared as fixed-length digests, whatever length was supplied
    assert calls == [(32, 32), (32, 32)]


def test_the_ingest_body_cannot_name_a_path(enabled, monkeypatch):
    started = []
    monkeypatch.setattr("src.api.admin.prepare_run", lambda *a, **k: started.append(a))
    auth = {"Authorization": f"Bearer {TOKEN}"}
    for body in ({"data_dir": "/etc"}, {"path": "/etc"}, {"source": "../x"}, {"force": True, "data_root": "/"}):
        res = enabled.post("/api/admin/datasets/o2c/ingest", headers=auth, json=body)
        assert res.status_code == 422, body
    assert started == []
    assert enabled.post("/api/admin/datasets/o2c/ingest", headers=auth, json={"mode": "partial"}).status_code == 422


def test_dataset_ids_that_are_not_ids_do_not_reach_the_database(enabled):
    auth = {"Authorization": f"Bearer {TOKEN}"}
    res = enabled.post("/api/admin/datasets/..%2F..%2Fetc/ingest", headers=auth, json={})
    assert res.status_code in (404, 409)


def test_the_old_ingest_endpoint_answers_410_and_ignores_the_body():
    client = TestClient(main_app)
    res = client.post("/api/ingest", json={"data_dir": "/Users/someone/data"})
    assert res.status_code == 410
    body = res.json()
    assert body["code"] == "gone" and "graphsense ingest" in body["detail"]
    assert "/Users" not in res.text
    assert client.post("/api/ingest").status_code == 410


def test_every_cli_command_of_this_workstream_is_registered():
    import click
    from click.testing import CliRunner

    from src.cli.main import cli, discover_commands

    names = discover_commands()
    assert {"ingest", "dataset", "db", "package"} <= set(names)
    runner = CliRunner()
    for args in (["ingest", "--help"], ["dataset", "--help"], ["db", "--help"]):
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, args
    listing = runner.invoke(cli, ["dataset", "--help"]).output
    for sub in ("list", "status", "rollback", "drop"):
        assert sub in listing
    assert "provision-roles" in runner.invoke(cli, ["db", "--help"]).output
    for flag in ("--data-root", "--force", "--dry-run", "--skip-hooks", "--max-reject-rate"):
        assert flag in runner.invoke(cli, ["ingest", "--help"]).output
    assert isinstance(cli, click.Group)


def test_the_ingest_command_refuses_an_unconfigured_data_root(monkeypatch):
    from click.testing import CliRunner

    from src.cli.main import cli, discover_commands

    discover_commands()
    with override_settings(DATA_ROOT=None):
        result = CliRunner().invoke(cli, ["ingest", "o2c", "--dry-run"])
    assert result.exit_code != 0
    assert "data_root_not_configured" in result.output
