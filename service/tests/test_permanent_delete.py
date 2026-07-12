"""Permanent plugin delete: rows, usage history, and artifact bytes are purged.

Uploads the same zip to two marketplaces (same content hash → shared,
content-addressed artifact). Deleting from the first purges rows + history but
keeps the shared bytes; deleting from the second garbage-collects the file.
Afterwards the same name@version can be republished.
"""

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app
from app.packaging import package_dir_to_zip

REPO = Path(__file__).resolve().parents[2]
HW2 = REPO / "examples" / "hello_world_2"


@pytest.fixture(scope="module", autouse=True)
async def _ready():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _artifact_path(sha256: str) -> Path:
    return Path(os.environ["ARTIFACTS_DIR"]) / sha256[:2] / f"{sha256}.zip"


async def test_permanent_delete_purges_history_and_artifacts():
    zip_bytes = package_dir_to_zip(HW2)

    async with _client() as c:
        await c.post("/api/auth/signup", json={
            "email": "purge@example.com", "username": "purger", "password": "pw12345"})
        token = (await c.post("/api/auth/login", json={
            "email": "purge@example.com", "username": "purger", "password": "pw12345"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        await c.post("/api/orgs", json={"name": "Purge Co", "slug": "purge-co"}, headers=h)
        for slug in ("del-a", "del-b"):
            r = await c.post("/api/orgs/purge-co/marketplaces",
                             json={"name": slug, "slug": slug, "visibility": "public"},
                             headers=h)
            assert r.status_code == 200, r.text
            up = await c.post(
                f"/api/marketplaces/{slug}/upload",
                files={"artifact": ("hw2.zip", zip_bytes, "application/zip")},
                headers=h,
            )
            assert up.status_code == 200, up.text

        entry = next(p for p in (await c.get("/mp/del-a/index.json")).json()["plugins"]
                     if p["name"] == "hello-world-2")
        sha = entry["sha256"]
        assert _artifact_path(sha).exists()

        # generate a download event so there is history beyond the publish event
        assert (await c.get(f"/mp/del-a/{entry['artifact']}")).status_code == 200

        # delete from del-a: rows + history gone, shared bytes survive (del-b)
        res = await c.delete("/api/marketplaces/del-a/plugins/hello-world-2", headers=h)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "deleted"
        assert body["versions_removed"] == 1
        assert body["artifacts_purged"] == 0
        assert body["events_purged"] >= 2  # publish + download
        assert _artifact_path(sha).exists()

        # gone from catalog, versions, and the Luna-facing index
        assert (await c.get("/api/catalog/del-a/hello-world-2")).status_code == 404
        assert (await c.get("/api/catalog/del-a/hello-world-2/versions")).status_code == 404
        idx = (await c.get("/mp/del-a/index.json")).json()
        assert all(p["name"] != "hello-world-2" for p in idx["plugins"])

        # delete from del-b: last reference → bytes garbage-collected
        res = await c.delete("/api/marketplaces/del-b/plugins/hello-world-2", headers=h)
        assert res.status_code == 200, res.text
        assert res.json()["artifacts_purged"] == 1
        assert not _artifact_path(sha).exists()

        # name@version is free again after a permanent delete
        up = await c.post(
            "/api/marketplaces/del-b/upload",
            files={"artifact": ("hw2.zip", zip_bytes, "application/zip")},
            headers=h,
        )
        assert up.status_code == 200, up.text
        assert _artifact_path(sha).exists()
