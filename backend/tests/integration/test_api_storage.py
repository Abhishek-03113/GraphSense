"""The HTTP surface on a real database: admin ingestion, dataset status, dataset isolation, roles."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from src.api.admin import mount_admin
from src.api.errors import install_error_handling
from src.config import reset_settings
from src.ingestion.runner import IngestOptions, ingest, prepare_run
from src.storage.engines import sync_dsn
from src.storage.roles import provision_roles

pytestmark = pytest.mark.integration

TOKEN = "s3cret-admin-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def admin_app(db, toy_root, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("DATA_ROOT", str(toy_root))
    reset_settings()
    app = FastAPI()
    install_error_handling(app)
    assert mount_admin(app)
    from src.api.datasets import router as datasets_router

    app.include_router(datasets_router)
    return app


@pytest.fixture
async def admin(admin_app):
    from src.db.engine import dispose_engine

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin_app), base_url="http://test") as c:
        yield c
    await dispose_engine()


async def test_admin_ingest_runs_in_the_background_and_reports_without_leaking(admin, toy_root, db):
    res = await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
    assert res.status_code == 202
    run_id = res.json()["run_id"]

    run = (await admin.get(f"/api/admin/runs/{run_id}", headers=AUTH)).json()
    assert run["status"] == "succeeded" and run["phase"] == "done"
    assert run["table_counts"] == {"authors": 3, "books": 3, "loans": 3, "members": 2}
    assert run["summary"]["rows"] == 11 and run["tables"]["books"]["loaded"] == 3

    listing = (await admin.get("/api/admin/runs", headers=AUTH, params={"dataset_id": "toy_library"})).json()
    assert [r["id"] for r in listing["runs"]] == [run_id]

    blob = json.dumps([run, listing])
    assert str(toy_root) not in blob and "toy-root" not in blob
    assert "SELECT" not in blob and "Traceback" not in blob and "psycopg" not in blob

    again = await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
    again_run = (await admin.get(f"/api/admin/runs/{again.json()['run_id']}", headers=AUTH)).json()
    assert again_run["status"] == "skipped"
    forced = await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={"force": True})
    assert (await admin.get(f"/api/admin/runs/{forced.json()['run_id']}", headers=AUTH)).json()["status"] == "succeeded"


async def test_admin_failures_are_sanitised(admin, toy_root, db):
    (toy_root / "toy-library" / "loans" / "part-0001.jsonl").write_text("garbage\n")
    res = await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
    run = (await admin.get(f"/api/admin/runs/{res.json()['run_id']}", headers=AUTH)).json()
    assert run["status"] == "failed" and run["error_code"] == "validation_failed"
    blob = json.dumps(run)
    assert str(toy_root) not in blob and "Traceback" not in blob and "SELECT" not in blob
    status = (await admin.get("/api/datasets/toy_library/status")).json()
    assert status["status"] == "failed" and status["last_run"]["error_code"] == "validation_failed"


async def test_admin_ingest_while_another_run_holds_the_dataset_is_409(admin, toy_root, db):
    held = await asyncio.to_thread(prepare_run, "toy_library", IngestOptions(data_root=toy_root))
    try:
        res = await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
        assert res.status_code == 409 and res.json()["code"] == "conflict"
    finally:
        held.release()


async def test_admin_rollback_and_unknown_things(admin, toy_root, db):
    await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
    assert (await admin.post("/api/admin/datasets/toy_library/rollbacks", headers=AUTH)).status_code == 409
    await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={"force": True})
    ok = await admin.post("/api/admin/datasets/toy_library/rollbacks", headers=AUTH)
    assert ok.status_code == 200 and ok.json()["status"] == "rolled_back"
    assert (await admin.post("/api/admin/datasets/nope/ingestions", headers=AUTH, json={})).status_code == 404
    assert (await admin.post("/api/admin/datasets/nope/rollbacks", headers=AUTH)).status_code == 404
    assert (await admin.get("/api/admin/runs/not-a-uuid", headers=AUTH)).status_code == 404
    assert (await admin.get("/api/admin/runs/00000000-0000-0000-0000-000000000000", headers=AUTH)).status_code == 404


async def test_admin_knowledge_refresh_runs_the_post_swap_hooks(admin, toy_root, db, monkeypatch):
    monkeypatch.setenv("POST_INGEST_HOOKS", "tests.fake_hooks:fake_post")
    reset_settings()
    from tests import fake_hooks

    fake_hooks.CALLS.clear()
    await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
    fake_hooks.CALLS.clear()
    res = await admin.post("/api/admin/datasets/toy_library/knowledge-refreshes", headers=AUTH, json={"force": True})
    assert res.status_code == 202
    run = (await admin.get(f"/api/admin/runs/{res.json()['run_id']}", headers=AUTH)).json()
    assert run["kind"] == "refresh" and run["status"] == "succeeded"
    assert fake_hooks.CALLS and fake_hooks.CALLS[0]["options"]["force"] is True


async def test_dataset_listing_and_status_follow_the_lifecycle(admin, toy_root, db):
    listing = (await admin.get("/api/datasets")).json()
    by_id = {d["id"]: d for d in listing}
    assert by_id["toy_library"]["status"] == "empty" and by_id["toy_library"]["last_ingested_at"] is None
    assert by_id["o2c"]["status"] == "empty"

    await admin.post("/api/admin/datasets/toy_library/ingestions", headers=AUTH, json={})
    by_id = {d["id"]: d for d in (await admin.get("/api/datasets")).json()}
    assert by_id["toy_library"]["status"] == "ready" and by_id["toy_library"]["last_ingested_at"]
    status = (await admin.get("/api/datasets/toy_library/status")).json()
    assert status["status"] == "ready" and status["package_version"] == "1.0.0"
    assert status["last_run"]["status"] == "succeeded" and status["record_counts"]["books"] == 3
    assert status["ai"]["knowledge"]["state"] in ("missing", "ready", "stale")
    blob = json.dumps([listing, status])
    assert str(toy_root) not in blob and "dataset_packages" not in blob and "fixtures" not in blob
    assert (await admin.get("/api/datasets/nope/status")).status_code == 404


async def test_status_is_loading_while_a_run_is_active(admin, toy_root, db):
    held = await asyncio.to_thread(prepare_run, "toy_library", IngestOptions(data_root=toy_root))
    try:
        status = (await admin.get("/api/datasets/toy_library/status")).json()
        assert status["status"] == "loading"
        # enough for a client to show where the load is
        assert status["last_run"]["status"] in ("queued", "running")
        assert status["last_run"]["phase"] and status["last_run"]["started_at"]
    finally:
        held.release()


async def test_status_works_before_the_database_is_migrated(admin, db):
    db.sql("DROP SCHEMA app CASCADE")
    status = (await admin.get("/api/datasets/toy_library/status")).json()
    assert status["status"] == "empty" and status["last_run"] is None


# --- two datasets in one database ----------------------------------------------------------


async def test_requests_read_the_dataset_they_name(db, toy_root, demo_root, client, monkeypatch):
    ingest("o2c", IngestOptions(data_root=demo_root))
    ingest("toy_library", IngestOptions(data_root=toy_root))

    default = (await client.get("/api/graph/summary")).json()
    toy = (await client.get("/api/graph/summary", headers={"X-GraphSense-Dataset": "toy_library"})).json()
    assert default["nodes"]["SalesOrder"] == 100
    assert toy["nodes"] == {"Author": 3, "Book": 3, "Member": 2, "Loan": 3}
    via_query = (await client.get("/api/graph/summary", params={"dataset": "toy_library"})).json()
    assert via_query == toy
    ents = (await client.get("/api/graph/node-types/Book/entities", params={"dataset": "toy_library"})).json()
    assert len(ents["entities"]) == 3
    # interleaved requests do not leak a search path into one another (pooled connections are reused)
    for _ in range(4):
        assert (await client.get("/api/graph/summary")).json() == default
        assert (await client.get("/api/graph/summary", params={"dataset": "toy_library"})).json() == toy


async def test_a_reload_is_visible_to_the_running_application(db, toy_root, client):
    ingest("toy_library", IngestOptions(data_root=toy_root))
    hdr = {"X-GraphSense-Dataset": "toy_library"}
    assert (await client.get("/api/graph/summary", headers=hdr)).json()["nodes"]["Member"] == 2
    record = json.loads((toy_root / "toy-library" / "members" / "part-0001.jsonl").read_text().splitlines()[0])
    record["memberId"] = "M66"
    (toy_root / "toy-library" / "members" / "part-0002.jsonl").write_text(json.dumps(record) + "\n")
    await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root))
    assert (await client.get("/api/graph/summary", headers=hdr)).json()["nodes"]["Member"] == 3


# --- roles -----------------------------------------------------------------------------------


def test_provisioned_roles_have_the_intended_privileges(db, toy_root):
    from src.storage.engines import get_owner_sync_engine

    ingest("toy_library", IngestOptions(data_root=toy_root))
    report = provision_roles(
        get_owner_sync_engine(), app_password="app-pw", readonly_password="ro-pw"
    )
    assert set(report.created) <= {"graphsense_app", "graphsense_ro"}
    # provisioning is repeatable
    provision_roles(get_owner_sync_engine(), app_password="app-pw", readonly_password="ro-pw")

    def connect(role: str, password: str):
        url = sync_dsn(db.dsn).replace("postgres@", f"{role}:{password}@")
        return create_engine(url)

    ro = connect("graphsense_ro", "ro-pw")
    with ro.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ds_toy_library.books")).scalar() == 3
        assert conn.execute(text("SHOW default_transaction_read_only")).scalar() == "on"
        with pytest.raises(ProgrammingError):
            conn.execute(text("SELECT * FROM app.datasets"))
    with ro.connect() as conn, pytest.raises(Exception, match="read-only"):
        conn.execute(text("CREATE TABLE ds_toy_library.x (a int)"))
    with ro.connect() as conn, pytest.raises(Exception, match="read-only"):
        conn.execute(text("DELETE FROM ds_toy_library.books"))
    ro.dispose()

    app = connect("graphsense_app", "app-pw")
    with app.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.datasets")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM ds_toy_library.books")).scalar() == 3
        conn.execute(text("UPDATE app.datasets SET updated_at = now()"))
    with app.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("DELETE FROM ds_toy_library.books"))
    app.dispose()


def test_new_generations_are_readable_by_the_roles_after_a_reload(db, toy_root):
    from src.storage.engines import get_owner_sync_engine

    provision_roles(get_owner_sync_engine(), readonly_password="ro-pw")
    ingest("toy_library", IngestOptions(data_root=toy_root))
    ingest("toy_library", IngestOptions(data_root=toy_root, force=True))
    url = sync_dsn(db.dsn).replace("postgres@", "graphsense_ro:ro-pw@")
    ro = create_engine(url)
    with ro.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ds_toy_library.books")).scalar() == 3
    ro.dispose()
