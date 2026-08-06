"""URL admission control for the browser tool.

**This is not optional.** The caller of this server is an LLM, and the server sits
*inside* the `hoover4` podman network, where `clickhouse:8123`, `temporal:7233`,
`manticore:9308` and every MCP server answer unauthenticated HTTP. A fetcher that will
retrieve any URL it is handed is, from inside that network, an arbitrary read of the
whole stack — and the URL can arrive from a web page the model was asked to summarise,
so "the user would not do that" is not a defence.

The rules, in order:

* scheme must be http or https — no `file://`, `chrome://`, `data:`, `ftp://`
* the host must resolve, and **every** address it resolves to must be public
* no loopback, link-local, private, multicast, reserved or unspecified address
* an explicit deny-list of the service names on this network, so a name that somehow
  resolves publicly still cannot be used to reach them

Resolution happens here and the check is applied to every returned address, which closes
the common bypass of a public name with a private A record (`localtest.me`,
`*.nip.io`). It does not close a DNS-rebinding race between this check and Chromium's
own resolution; the deny-list and the network's own lack of routing to anything
interesting are what stand behind it.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

log = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Hostnames on the `hoover4` network that must never be fetched, whatever they resolve
#: to. Belt to the address check's braces, and the thing that makes the intent readable.
_DENIED_HOSTS = frozenset(
    {
        "clickhouse", "manticore", "temporal", "temporal-ui", "redis", "zookeeper",
        "minio-s3", "minio", "hoover4-vllm", "hoover4-ai-server", "hoover4-worker",
        "hoover4-website", "temporal-cassandra", "temporal-elasticsearch",
        "hoover4-mcp-collections", "hoover4-mcp-ddg", "hoover4-mcp-whois",
        "hoover4-mcp-wikipedia", "hoover4-mcp-metasearch", "hoover4-mcp-browser",
        "localhost", "metadata.google.internal",
    }
)


class UrlNotAllowed(ValueError):
    """The URL is refused before any network request is made."""


def _address_is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_url(url: str) -> str:
    """Return the URL if it may be fetched, else raise :class:`UrlNotAllowed`.

    Resolves the host and requires *every* address to be public, so a public name with a
    private A record is refused rather than followed.
    """
    try:
        parsed = urlparse((url or "").strip())
    except ValueError as exc:
        raise UrlNotAllowed(f"unparseable URL: {exc}") from exc

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowed(
            f"scheme {parsed.scheme!r} is not allowed; only http and https are fetchable"
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlNotAllowed("URL has no host")

    if host in _DENIED_HOSTS or host.endswith(".internal"):
        raise UrlNotAllowed(f"{host!r} is an internal service and must not be fetched")

    # A literal address skips resolution but not the check.
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        if os.getenv("BROWSER_SKIP_DNS_CHECK") == "1":
            # Escape hatch for offline unit tests only. Never set in compose.
            return url
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UrlNotAllowed(f"{host!r} does not resolve: {exc}") from exc
        addresses = sorted({info[4][0] for info in infos})

    if not addresses:
        raise UrlNotAllowed(f"{host!r} resolved to no addresses")

    for address in addresses:
        if not _address_is_public(address):
            raise UrlNotAllowed(
                f"{host!r} resolves to the non-public address {address}; refusing to "
                "fetch anything on a private or loopback network"
            )

    return url
