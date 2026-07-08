"""Bundles: curated plugin groups with their own version and explicit pins.

Covers the core rules:
- pins must reference existing (plugin, version) pairs
- bundle versions are immutable
- a plugin publishing a newer version does NOT move any bundle pin
- the Luna index serves bundles with fully resolved items (artifact + sha256)
- yank hides a bundle version from the index
"""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app
from app.packaging import package_dir_to_zip

REPO = Path(__file__).resolve().parents[2]
HW2 = REPO / "examples" / "hello_world_2"

EMAIL, USER, PW = "bundler@example.com", "bundler", "pw12345"
ORG, MP = "bundle-co", "bundle-mp"


@pytest.fixture(scope="module", autouse=True)
async def _ready():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _zip_with_version(version: str) -> bytes:
    """A valid plugin zip whose manifest carries the given version."""
    base = package_dir_to_zip(HW2)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith("luna-plugin.toml"):
                text = data.decode()
                lines = [
                    f'version = "{version}"' if line.strip().startswith("version") else line
                    for line in text.splitlines()
                ]
                data = "\n".join(lines).encode()
            dst.writestr(info, data)
    return out.getvalue()


async def _setup(c: AsyncClient) -> dict:
    await c.post("/api/auth/signup", json={"email": EMAIL, "username": USER, "password": PW})
    token = (await c.post("/api/auth/login", json={"email": EMAIL, "password": PW})).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    await c.post("/api/orgs", json={"name": "Bundle Co", "slug": ORG}, headers=h)
    await c.post(f"/api/orgs/{ORG}/marketplaces",
                 json={"name": "Bundle MP", "slug": MP, "visibility": "public"}, headers=h)
    return h


async def _upload(c: AsyncClient, h: dict, version: str) -> str:
    zb = _zip_with_version(version)
    r = await c.post(f"/api/marketplaces/{MP}/upload",
                     files={"artifact": (f"p-{version}.zip", zb, "application/zip")}, headers=h)
    assert r.status_code == 200, r.text
    return hashlib.sha256(zb).hexdigest()


async def test_bundle_lifecycle():
    async with _client() as c:
        h = await _setup(c)
        sha_010 = await _upload(c, h, "0.1.0")

        # -- create bundle pinned at 0.1.0
        r = await c.post(f"/api/marketplaces/{MP}/bundles", json={
            "name": "starter-pack",
            "title": "Starter Pack",
            "version": "1.0.0",
            "description": "Everything to get going",
            "tags": ["starter"],
            "icon_url": "https://example.com/pack.png",
            "items": [{"plugin_name": "hello-world-2", "version": "0.1.0"}],
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["latest_version"] == "1.0.0"
        assert body["items"][0]["version"] == "0.1.0"

        # -- browse endpoints
        lst = (await c.get(f"/api/catalog/{MP}/bundles")).json()
        assert [b["name"] for b in lst] == ["starter-pack"]
        detail = (await c.get(f"/api/catalog/{MP}/bundles/starter-pack")).json()
        assert detail["title"] == "Starter Pack"

        # -- luna index: resolved items with artifact + sha256
        idx = (await c.get(f"/mp/{MP}/index.json")).json()
        assert len(idx["bundles"]) == 1
        bentry = idx["bundles"][0]
        assert bentry["version"] == "1.0.0"
        item = bentry["items"][0]
        assert item["artifact"] == "plugins/hello-world-2/0.1.0/artifact.zip"
        assert item["sha256"] == sha_010

        # -- pin validation: unknown plugin / unknown version → 400
        bad = await c.post(f"/api/marketplaces/{MP}/bundles", json={
            "name": "bad", "title": "Bad", "items": [{"plugin_name": "ghost", "version": "1.0.0"}],
        }, headers=h)
        assert bad.status_code == 400
        bad2 = await c.post(f"/api/marketplaces/{MP}/bundles", json={
            "name": "bad2", "title": "Bad2", "items": [{"plugin_name": "hello-world-2", "version": "9.9.9"}],
        }, headers=h)
        assert bad2.status_code == 400


async def test_plugin_upgrade_does_not_move_bundle_pin():
    async with _client() as c:
        token = (await c.post("/api/auth/login", json={"email": EMAIL, "password": PW})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # plugin releases 0.2.0
        await _upload(c, h, "0.2.0")
        # plugin's own latest moved...
        plugin = (await c.get(f"/api/catalog/{MP}/hello-world-2")).json()
        assert plugin["latest_version"] == "0.2.0"
        # ...but the bundle still pins 0.1.0 (both in API and in luna index)
        detail = (await c.get(f"/api/catalog/{MP}/bundles/starter-pack")).json()
        assert detail["items"][0]["version"] == "0.1.0"
        assert detail["items"][0]["latest_available"] == "0.2.0"
        idx = (await c.get(f"/mp/{MP}/index.json")).json()
        assert idx["bundles"][0]["items"][0]["version"] == "0.1.0"


async def test_new_bundle_version_updates_pins_and_immutability():
    async with _client() as c:
        token = (await c.post("/api/auth/login", json={"email": EMAIL, "password": PW})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # deliberate editor action: publish bundle 1.1.0 pinning plugin 0.2.0
        r = await c.post(f"/api/marketplaces/{MP}/bundles/starter-pack/versions", json={
            "version": "1.1.0",
            "items": [{"plugin_name": "hello-world-2", "version": "0.2.0"}],
        }, headers=h)
        assert r.status_code == 200, r.text
        idx = (await c.get(f"/mp/{MP}/index.json")).json()
        assert idx["bundles"][0]["version"] == "1.1.0"
        assert idx["bundles"][0]["items"][0]["version"] == "0.2.0"

        # immutability: same bundle version again → 409
        dup = await c.post(f"/api/marketplaces/{MP}/bundles/starter-pack/versions", json={
            "version": "1.1.0",
            "items": [{"plugin_name": "hello-world-2", "version": "0.1.0"}],
        }, headers=h)
        assert dup.status_code == 409

        # version history shows both
        vers = (await c.get(f"/api/catalog/{MP}/bundles/starter-pack/versions")).json()
        assert {v["version"] for v in vers} == {"1.0.0", "1.1.0"}


async def test_yank_hides_from_index():
    async with _client() as c:
        token = (await c.post("/api/auth/login", json={"email": EMAIL, "password": PW})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # yank 1.1.0 → index falls back to 1.0.0
        r = await c.post(f"/api/marketplaces/{MP}/bundles/starter-pack/versions/1.1.0/yank",
                         json={"yanked": True}, headers=h)
        assert r.status_code == 200
        idx = (await c.get(f"/mp/{MP}/index.json")).json()
        assert idx["bundles"][0]["version"] == "1.0.0"

        # un-yank restores
        await c.post(f"/api/marketplaces/{MP}/bundles/starter-pack/versions/1.1.0/yank",
                     json={"yanked": False}, headers=h)
        idx = (await c.get(f"/mp/{MP}/index.json")).json()
        assert idx["bundles"][0]["version"] == "1.1.0"


async def test_permissions_and_delete():
    async with _client() as c:
        # an unrelated user cannot manage bundles here
        await c.post("/api/auth/signup", json={
            "email": "rando@example.com", "username": "rando", "password": "pw12345"})
        rando = (await c.post("/api/auth/login", json={
            "email": "rando@example.com", "password": "pw12345"})).json()["access_token"]
        r = await c.post(f"/api/marketplaces/{MP}/bundles", json={
            "name": "evil", "title": "Evil",
            "items": [{"plugin_name": "hello-world-2", "version": "0.1.0"}],
        }, headers={"Authorization": f"Bearer {rando}"})
        assert r.status_code == 403

        # owner deletes the bundle; member plugin survives
        token = (await c.post("/api/auth/login", json={"email": EMAIL, "password": PW})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.delete(f"/api/marketplaces/{MP}/bundles/starter-pack", headers=h)
        assert r.status_code == 200
        assert (await c.get(f"/api/catalog/{MP}/bundles")).json() == []
        assert (await c.get(f"/api/catalog/{MP}/hello-world-2")).status_code == 200
        idx = (await c.get(f"/mp/{MP}/index.json")).json()
        assert idx["bundles"] == []
