"""Integration test: seed → serve the Luna-v0 protocol → verify the trust gate.

This is the same check Luna's installer makes: pull index.json, fetch each
artifact, assert sha256(bytes) == the index entry's sha256.
"""

import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app
from app.seed_core import OFFICIAL_MP_ID, seed_core_plugins


@pytest.fixture(scope="module", autouse=True)
async def _seeded():
    await init_db()
    await seed_core_plugins()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_identity_doc():
    async with _client() as c:
        r = await c.get("/mp/official/.well-known/luna-marketplace.json")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == OFFICIAL_MP_ID
        assert body["protocol_version"] == "0"


async def test_index_lists_hello_world():
    async with _client() as c:
        r = await c.get("/mp/official/index.json")
        assert r.status_code == 200
        body = r.json()
        names = [p["name"] for p in body["plugins"]]
        assert "hello-world" in names
        entry = next(p for p in body["plugins"] if p["name"] == "hello-world")
        assert entry["version"] == "0.1.0"
        assert entry["artifact"] == "plugins/hello-world/0.1.0/artifact.zip"
        assert len(entry["sha256"]) == 64


async def test_artifact_hash_matches_index_the_trust_gate():
    async with _client() as c:
        idx = (await c.get("/mp/official/index.json")).json()
        for entry in idx["plugins"]:
            art = await c.get(f"/mp/official/{entry['artifact']}")
            assert art.status_code == 200, entry["name"]
            actual = hashlib.sha256(art.content).hexdigest()
            assert actual == entry["sha256"], f"hash mismatch for {entry['name']}"


async def test_seed_is_idempotent():
    # Re-running the seeder must not duplicate or change hashes.
    before = (await _index())["plugins"]
    await seed_core_plugins()
    after = (await _index())["plugins"]
    assert len(before) == len(after)
    assert {p["name"]: p["sha256"] for p in before} == {p["name"]: p["sha256"] for p in after}


async def _index():
    async with _client() as c:
        return (await c.get("/mp/official/index.json")).json()
