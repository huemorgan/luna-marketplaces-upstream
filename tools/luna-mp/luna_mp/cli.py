"""CLI interface for luna-mp."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import click

from .build import build_marketplace
from .signing import KeyPair
from .verify import verify_marketplace


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Luna Marketplace reference tooling — build, verify, and serve static marketplaces."""
    pass


@main.command()
@click.option("--out", "-o", type=click.Path(), default="./keys", help="Output directory for keys")
@click.option("--name", "-n", default="marketplace", help="Key file prefix")
def keygen(out: str, name: str):
    """Generate an Ed25519 keypair for marketplace or publisher signing."""
    output = Path(out)
    kp = KeyPair.generate()
    kp.save(output, name)
    click.echo(f"Generated keypair in {output}/")
    click.echo(f"  Private: {output}/{name}.key")
    click.echo(f"  Public:  {output}/{name}.pub")
    click.echo(f"  Key ID:  {kp.public_hex[:32]}...")


@main.command()
@click.argument("source", type=click.Path(exists=True))
@click.option("--out", "-o", type=click.Path(), required=True, help="Output directory")
@click.option("--marketplace-key", "-k", type=click.Path(exists=True), required=True, help="Marketplace signing key")
@click.option("--publisher-key", type=click.Path(exists=True), default=None, help="Publisher signing key (separate from marketplace)")
@click.option("--name", default="My Marketplace", help="Marketplace display name")
@click.option("--id", "mp_id", default=None, help="Marketplace UUID (generated if omitted)")
def build(source: str, out: str, marketplace_key: str, publisher_key: str | None, name: str, mp_id: str | None):
    """Build a static marketplace from a directory of plugin folders."""
    source_path = Path(source)
    output_path = Path(out)
    key = KeyPair.from_file(Path(marketplace_key))
    pub_key = KeyPair.from_file(Path(publisher_key)) if publisher_key else None
    marketplace_id = mp_id or str(uuid.uuid4())

    try:
        result = build_marketplace(
            source_dir=source_path,
            output_dir=output_path,
            key=key,
            marketplace_id=marketplace_id,
            marketplace_name=name,
            publisher_key=pub_key,
        )
        click.echo(f"Built marketplace at {result}/")
        click.echo(f"  ID: {marketplace_id}")
        click.echo(f"  Plugins: {len(list(source_path.iterdir()))}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--pinned-key", "-p", multiple=True, help="Pinned public key (hex)")
@click.option("--no-freshness", is_flag=True, help="Skip timestamp freshness check")
@click.option("--json-output", is_flag=True, help="Output JSON instead of human-readable")
def verify(target: str, pinned_key: tuple[str, ...], no_freshness: bool, json_output: bool):
    """Verify a marketplace directory for integrity, signatures, and freshness."""
    target_path = Path(target)
    pinned = list(pinned_key) if pinned_key else None

    result = verify_marketplace(
        target=target_path,
        pinned_keys=pinned,
        check_freshness=not no_freshness,
    )

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        if result.valid:
            click.echo(f"✓ Marketplace valid")
            click.echo(f"  Plugins: {result.plugins_checked}")
            click.echo(f"  Versions: {result.versions_checked}")
        else:
            click.echo(f"✗ Marketplace INVALID — {len(result.errors)} error(s):")
            for err in result.errors:
                click.echo(f"  [{err.code.value}] {err.message}")
                if err.path:
                    click.echo(f"    at: {err.path}")

        if result.warnings:
            click.echo(f"\n  Warnings:")
            for w in result.warnings:
                click.echo(f"    ⚠ {w}")

    sys.exit(0 if result.valid else 1)


@main.command()
@click.argument("directory", type=click.Path(exists=True))
@click.option("--port", "-p", default=8480, help="Port to serve on")
@click.option("--host", default="localhost", help="Host to bind to")
def serve(directory: str, port: int, host: str):
    """Serve a marketplace directory over HTTP (dev server)."""
    import http.server
    import functools
    import os

    os.chdir(directory)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    server = http.server.HTTPServer((host, port), handler)
    click.echo(f"Serving marketplace at http://{host}:{port}/")
    click.echo(f"  Identity: http://{host}:{port}/.well-known/luna-marketplace.json")
    click.echo(f"  Index:    http://{host}:{port}/index.json")
    click.echo("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")


if __name__ == "__main__":
    main()
