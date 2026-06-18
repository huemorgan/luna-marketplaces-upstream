# 01 — Live service serves the Luna-v0 protocol

**Goal:** the deployed Render service exposes the marketplace protocol Luna
consumes, and the artifact's bytes match the advertised hash (the trust gate).

## Preconditions
- Service deployed and Live on Render with the persistent disk mounted at `/data`.

## Steps (browser + network)
1. Open `https://luna-marketplaces.onrender.com/mp/official/.well-known/luna-marketplace.json`.
2. Open `https://luna-marketplaces.onrender.com/mp/official/index.json`.
3. From the index, note `hello-world`'s `artifact` path and `sha256`.
4. Download `https://luna-marketplaces.onrender.com/mp/official/<artifact>` and
   compute its sha256.

## Expected
- Identity doc returns `{id, name, protocol_version: "0"}` with `name` = "Luna Official (dev)".
- index.json lists `hello-world` v0.1.0 with a 64-hex `sha256` and
  `artifact: plugins/hello-world/0.1.0/artifact.zip`.
- Downloaded artifact's sha256 **equals** the index `sha256`.
- The artifact zip has exactly one top-level dir `hello_world/` containing
  `__init__.py` and `luna-plugin.toml`.

## Pass/Fail
- PASS: all three docs resolve and the hashes match.
- FAIL: any 404/500, empty `plugins`, or hash mismatch.
