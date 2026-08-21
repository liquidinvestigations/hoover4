# Networking

## Contents

- DNS before the application
- Container names and networks
- Ports are ini keys

## DNS before the application

"One container can't reach the internet" is a DNS question first. The `hoover4` network
once had no upstream resolvers, so aardvark-dns forwarded to the host's `127.0.0.53` stub
and silently stopped answering external queries — while internal container-name resolution
kept working. The pipeline looked healthy and only internet-facing things (cargo fetching
crates.io, the MCP search tools) hung.

Diagnose by comparing an internal lookup against an external one from inside the container,
and by checking the network itself:

    podman network inspect hoover4 | grep network_dns_servers
    docker exec <c> getent hosts clickhouse
    docker exec <c> getent hosts crates.io

Never fix this with a per-container `dns:` pin in compose — that cuts the container off
from aardvark and breaks internal resolution. `deploy.py ensure_network` pins and repairs
resolvers at the network level.

## Container names and networks

Containers on separate networks cannot address each other by name. `ai_services` is a
private network with no dependency on the main stack, which is the point of the CPU twins
on the main side. A rootless podman container cannot reach its host's LAN IP at all — it
hangs rather than refuses. `host.containers.internal` is the routable name for the host.

## Ports are ini keys

Every port is a key in `hoover4.ini`, not a literal to be remembered — except the website,
which stays 12345. A "connection refused" against a hard-coded port number is usually the
port having moved, not the service being down.
