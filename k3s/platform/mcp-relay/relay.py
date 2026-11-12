#!/usr/bin/env python3
"""Forward TCP connections from host loopback ports to Services of a Hoover installation.

The relay pod runs with runc in the host network of the home node (install-relay.py). It reads the routes from the file
that RELAY_ROUTES names: a JSON list of {"name", "listen", "target"}, where listen is <address>:<port> and target is
<service host>:<port>. Each accepted connection gets one connection to its target, and the relay copies the bytes in
both directions until one side closes. The relay reads no request content, so the MCP servers keep their own
authentication. It prints one JSON line for each route that it opens and for each target that refuses a connection.
"""
import asyncio
import json
import os
import sys


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


def handler(route):
    host, port = route['target'].rsplit(':', 1)

    async def handle(client_reader, client_writer):
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 10)
        except (OSError, asyncio.TimeoutError) as error:
            print(json.dumps({'route': route['name'], 'target': route['target'], 'error': str(error) or type(error).__name__}), flush=True)
            client_writer.close()
            return
        await asyncio.gather(pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer))
    return handle


async def main():
    routes = json.loads(open(os.environ.get('RELAY_ROUTES', '/etc/relay/routes.json')).read())
    servers = []
    for route in routes:
        address, port = route['listen'].rsplit(':', 1)
        servers.append(await asyncio.start_server(handler(route), address, int(port), reuse_address=True))
        print(json.dumps({'route': route['name'], 'listen': route['listen'], 'target': route['target']}), flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except OSError as error:
        sys.exit(f'the relay cannot open a route: {error}')
