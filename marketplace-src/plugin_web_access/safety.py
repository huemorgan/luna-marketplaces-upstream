"""Basic SSRF guard for web-access tools (005.902 follow-up).

The 005.902 plan specifies open internet access. This adds a *default-on* guard
against the genuinely dangerous targets — loopback, RFC1918 private ranges,
link-local (incl. the cloud-metadata IP 169.254.169.254), and reserved/multicast
addresses — so a prompt-injected `web_fetch`/`http_request` can't pivot to
internal services or steal instance credentials.

Opt out with `LUNA_WEB_ALLOW_PRIVATE=1` if you genuinely need the agent to reach
LAN/localhost hosts (matches the plan's "open access" intent, but as a choice).

Note: this resolves DNS and inspects the resolved IPs. It is a pragmatic guard,
not airtight against DNS-rebinding (the connect may resolve differently) — fine
for a local single-user agent; revisit if hosted/multi-tenant.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


def _allow_private() -> bool:
    return os.environ.get("LUNA_WEB_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "yes", "on")


def blocked_reason(url: str) -> str | None:
    """Return a human-readable reason if `url` targets a non-public address,
    else None. Honors the LUNA_WEB_ALLOW_PRIVATE opt-out."""
    if _allow_private():
        return None
    host = urlparse(url).hostname
    if not host:
        return None  # malformed; the caller's own validation handles it
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None  # unresolvable — let the HTTP layer fail naturally
    for info in infos:
        ip_str = info[4][0]
        try:
            addr = ipaddress.ip_address(ip_str.split("%")[0])  # strip zone id
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return (
                f"blocked: '{host}' resolves to non-public address {ip_str}. "
                f"Set LUNA_WEB_ALLOW_PRIVATE=1 to allow internal/loopback targets."
            )
    return None
