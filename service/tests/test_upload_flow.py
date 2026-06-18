"""Integration test: a developer uploads a plugin zip → it's served to Luna.

Full runtime path with no repo commit: signup → create org → create marketplace
→ upload hello-world-2 zip → it appears in that marketplace's index.json with a
matching sha256, and the artifact downloads + bumps the download counter.
"""

import hashlib
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


async def test_developer_upload_then_served_to_luna():
    zip_bytes = package_dir_to_zip(HW2)
    expected_sha = hashlib.sha256(zip_bytes).hexdigest()

    async with _client() as c:
        # signup
        await c.post("/api/auth/signup", json={
            "email": "dev@example.com", "username": "devuser", "password": "pw12345"})
        token = (await c.post("/api/auth/login", json={
            "email": "dev@example.com", "username": "devuser", "password": "pw12345"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # org + marketplace
        await c.post("/api/orgs", json={"name": "Dev Co", "slug": "dev-co"}, headers=h)
        r = await c.post("/api/orgs/dev-co/marketplaces",
                         json={"name": "Dev Plugins", "slug": "dev-plugins", "visibility": "public"},
                         headers=h)
        assert r.status_code == 200, r.text

        # upload just the zip (manifest read from inside)
        up = await c.post(
            "/api/marketplaces/dev-plugins/upload",
            files={"artifact": ("hello-world-2.zip", zip_bytes, "application/zip")},
            headers=h,
        )
        assert up.status_code == 200, up.text
        assert up.json()["version"] == "0.1.0"

        # served in the index with the right hash
        idx = (await c.get("/mp/dev-plugins/index.json")).json()
        entry = next(p for p in idx["plugins"] if p["name"] == "hello-world-2")
        assert entry["sha256"] == expected_sha

        # artifact downloads and the bytes verify
        art = await c.get(f"/mp/dev-plugins/{entry['artifact']}")
        assert art.status_code == 200
        assert hashlib.sha256(art.content).hexdigest() == expected_sha

        # download counter incremented
        detail = (await c.get("/api/catalog/dev-plugins/hello-world-2")).json()
        assert detail["download_count"] >= 1


async def test_immutability_same_version_conflict():
    zip_bytes = package_dir_to_zip(HW2)
    async with _client() as c:
        token = (await c.post("/api/auth/login", json={
            "email": "dev@example.com", "username": "devuser", "password": "pw12345"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        # re-uploading identical bytes for an existing version is a 409
        up = await c.post(
            "/api/marketplaces/dev-plugins/upload",
            files={"artifact": ("hello-world-2.zip", zip_bytes, "application/zip")},
            headers=h,
        )
        assert up.status_code == 409
