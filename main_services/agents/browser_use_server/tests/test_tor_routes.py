"""The Tor routes of `read_page`: the route list, the order, the SOCKS5 relay, the browser
context of a Tor attempt, and the attempts of one URL.

None of this needs Chromium or Tor. The Tor port is a small SOCKS5 server in the test that
records the user name and echoes the data.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import time
from types import SimpleNamespace

import pytest

from browser_use_server import read_page, special_browser, tor_routes
from browser_use_server.read_page import PageRead
from browser_use_server.special_browser import Lease, SpecialBrowser


def _run_cdp(command, answer: dict):
    try:
        command.send(answer)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("the command did not finish")


class TestParse:
    def test_names_hosts_and_ports(self):
        routes = tor_routes.parse_routes(
            " tor-fr=127.0.0.1:9101, 127.0.0.2:9102 ,9103,,tor-de=127.0.0.1:9104")
        assert routes == [
            tor_routes.Route("tor-fr", "127.0.0.1", 9101),
            tor_routes.Route("tor-9102", "127.0.0.2", 9102),
            tor_routes.Route("tor-9103", "127.0.0.1", 9103),
            tor_routes.Route("tor-de", "127.0.0.1", 9104),
        ]

    def test_bad_entries_are_skipped(self):
        assert tor_routes.parse_routes("x=127.0.0.1:port,70000,direct=9050") == []
        assert tor_routes.parse_routes("a=9050,a=9051") == [tor_routes.Route("a", "127.0.0.1", 9050)]
        assert tor_routes.parse_routes("") == []


@pytest.fixture
def routes(monkeypatch):
    """Three Tor routes and an empty cooldown."""
    configured = tor_routes.parse_routes("tor-a=9101,tor-b=9102,tor-c=9103")
    monkeypatch.setattr(tor_routes, "ROUTES", configured)
    monkeypatch.setattr(tor_routes, "_cooldown", {})
    return configured


class TestOrder:
    def test_direct_first_then_two_tor_routes(self, routes):
        for _ in range(20):
            names = tor_routes.order("a.example")
            assert names[0] == "direct" and len(names) == 3
            assert len(set(names[1:])) == 2 and set(names[1:]) <= {"tor-a", "tor-b", "tor-c"}

    def test_a_blocked_route_goes_last_for_that_host_only(self, routes):
        tor_routes.record("a.example", "direct", True)
        tor_routes.record("a.example", "tor-a", True)
        tor_routes.record("a.example", "tor-b", True)
        names = tor_routes.order("a.example")
        assert names[:2] == ["tor-c", "direct"] and names[2] in ("tor-a", "tor-b")
        assert tor_routes.order("b.example")[0] == "direct"
        tor_routes.record("a.example", "direct", False)
        assert tor_routes.order("a.example")[:2] == ["direct", "tor-c"]
        assert tor_routes.health()["cooldowns"] == 2

    def test_without_routes_only_direct(self, monkeypatch):
        monkeypatch.setattr(tor_routes, "ROUTES", [])
        assert tor_routes.order("a.example") == ["direct"]


class TestPublicName:
    @pytest.mark.parametrize("name", [
        "127.0.0.1", "10.1.2.3", "192.168.1.1", "169.254.169.254", "100.64.0.1", "::1",
        "[::1]", "fe80::1", "0.0.0.0", "localhost", "a.localhost", "printer.local",
        "metadata.google.internal", "intranet", "", "router.lan",
    ])
    def test_not_public(self, name):
        assert not tor_routes.public_name(name)

    @pytest.mark.parametrize("name", ["example.com", "93.184.215.14",
                                      "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"])
    def test_public(self, name):
        assert tor_routes.public_name(name)

    def test_a_host_that_resolves_to_loopback_is_not_public(self, monkeypatch):
        monkeypatch.setattr(tor_routes.socket, "getaddrinfo",
                            lambda host, port: [(0, 0, 0, "", ("127.0.0.1", 0))])
        assert not tor_routes.public_host("rebind.example")


class FakeTor:
    """A SOCKS5 port that asks for a user name, records it, answers success and echoes."""

    def __init__(self):
        self.users: list[str] = []
        self.requests: list[bytes] = []
        self.server = None
        self.port = 0

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self.server.close()

    async def _serve(self, reader, writer):
        try:
            assert await reader.readexactly(3) == b"\x05\x01\x02"
            writer.write(b"\x05\x02")
            _version, size = await reader.readexactly(2)
            self.users.append((await reader.readexactly(size)).decode())
            size = (await reader.readexactly(1))[0]
            await reader.readexactly(size)
            writer.write(b"\x01\x00")
            head = await reader.readexactly(5)
            rest = await reader.readexactly(head[4] + 2)
            self.requests.append(head + rest)
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            while data := await reader.read(1024):
                writer.write(data)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


async def _connect(port: int, kind: int, address: bytes, dest_port: int = 80):
    """A SOCKS5 CONNECT through the relay on `port`. Returns `(reply, reader, writer)`."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"\x05\x01\x00")
    assert await reader.readexactly(2) == b"\x05\x00"
    writer.write(bytes([5, 1, 0, kind]) + address + dest_port.to_bytes(2, "big"))
    reply = await reader.readexactly(10)
    return reply, reader, writer


def _domain(name: str) -> bytes:
    return bytes([len(name)]) + name.encode()


class TestRelay:
    def test_the_block_end_closes_the_tor_connection_of_an_open_stream(self):
        """A keep-alive stream of Chromium stays open past the attempt. The block end must
        close its Tor connection too."""
        closed = asyncio.Event()

        async def tor(reader, writer):
            await reader.readexactly(3)
            writer.write(b"\x05\x02")
            _version, size = await reader.readexactly(2)
            await reader.readexactly(size)
            await reader.readexactly((await reader.readexactly(1))[0])
            writer.write(b"\x01\x00")
            head = await reader.readexactly(5)
            await reader.readexactly(head[4] + 2)
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            while await reader.read(100):
                pass
            closed.set()

        async def run():
            server = await asyncio.start_server(tor, "127.0.0.1", 0)
            route = tor_routes.Route("tor-x", "127.0.0.1", server.sockets[0].getsockname()[1])
            async with tor_routes.SocksRelay(route) as relay:
                reply, _reader, writer = await _connect(relay.port, 3, _domain("example.com"))
                assert reply[1] == 0
                writer.write(b"GET / HTTP/1.1\r\n\r\n")
                await writer.drain()
                await asyncio.sleep(0.1)
            # Chromium's side is still open here.
            await asyncio.wait_for(closed.wait(), 3)
            assert relay._writers == set()
            writer.close()
            server.close()

        asyncio.run(run())

    def test_each_relay_sends_a_new_user_name_and_relays_the_data(self):
        async def run():
            async with FakeTor() as tor:
                route = tor_routes.Route("tor-x", "127.0.0.1", tor.port)
                async with tor_routes.SocksRelay(route) as first:
                    reply, reader, writer = await _connect(first.port, 3, _domain("example.com"))
                    assert reply[1] == 0
                    writer.write(b"ping")
                    assert await reader.readexactly(4) == b"ping"
                    writer.close()
                    # A second connection of the same attempt uses the same circuit.
                    reply, _r, writer = await _connect(first.port, 3, _domain("example.org"))
                    writer.close()
                    assert first.proxy_server == f"socks5://127.0.0.1:{first.port}"
                async with tor_routes.SocksRelay(route) as second:
                    reply, _r, writer = await _connect(second.port, 3, _domain("example.com"))
                    writer.close()
                return tor, first.username, second.username

        tor, first, second = asyncio.run(run())
        assert tor.users == [first, first, second] and first != second
        assert tor.requests[0] == b"\x05\x01\x00\x03" + _domain("example.com") + b"\x00\x50"

    @pytest.mark.parametrize("kind,address", [
        (1, ipaddress.IPv4Address("127.0.0.1").packed),
        (1, ipaddress.IPv4Address("192.168.1.1").packed),
        (4, ipaddress.IPv6Address("::1").packed),
        (3, _domain("localhost")),
        (3, _domain("intranet")),
    ])
    def test_a_destination_that_is_not_public_is_refused(self, kind, address):
        async def run():
            async with FakeTor() as tor:
                route = tor_routes.Route("tor-x", "127.0.0.1", tor.port)
                async with tor_routes.SocksRelay(route) as relay:
                    reply, _r, writer = await _connect(relay.port, kind, address)
                    writer.close()
                    return reply, tor.users, relay.refused

        reply, users, refused = asyncio.run(run())
        assert reply[1] == 2 and users == [] and refused == 1

    def test_a_tor_port_that_is_down_gives_a_failure_reply(self):
        async def run():
            route = tor_routes.Route("tor-x", "127.0.0.1", 1)
            async with tor_routes.SocksRelay(route) as relay:
                reply, _r, writer = await _connect(relay.port, 3, _domain("example.com"))
                writer.close()
                return reply

        assert asyncio.run(run())[1] == 1


class ContextBrowser:
    """A browser connection that makes contexts and their targets."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def send(self, command):
        cmd = next(command)
        method, params = cmd["method"], cmd.get("params", {})
        self.calls.append((method, params))
        if method == "Target.createBrowserContext":
            return _run_cdp(command, {"browserContextId": "CTX1"})
        if method == "Target.createTarget":
            return _run_cdp(command, {"targetId": "TOR1"})
        return _run_cdp(command, {})


class TestContextTab:
    def test_the_context_has_the_proxy_and_the_bypass_list_and_is_disposed(self, monkeypatch):
        import nodriver

        tabs = []

        class Tab(SimpleNamespace):
            async def aclose(self):
                self.closed = True

        monkeypatch.setattr(nodriver, "Tab", lambda target, parent: tabs.append(
            Tab(target=target)) or tabs[-1])
        browser = ContextBrowser()
        pool = SpecialBrowser("_reader", 2)
        lease = Lease(tab=None, target_id="T0", died=asyncio.Event(), browser=browser)

        async def run():
            async with pool.context_tab(lease, "socks5://127.0.0.1:5555",
                                        tor_routes.CONTEXT_BYPASS) as tab:
                assert tab.target == "TOR1" and "TOR1" in pool._leased
            assert pool._leased == set()

        asyncio.run(run())
        methods = [m for m, _ in browser.calls]
        assert methods == ["Target.createBrowserContext", "Target.createTarget",
                           "Target.closeTarget", "Target.disposeBrowserContext"]
        create = browser.calls[0][1]
        assert create["proxyServer"] == "socks5://127.0.0.1:5555"
        assert create["proxyBypassList"].startswith("<-loopback>;")
        assert browser.calls[1][1]["browserContextId"] == "CTX1"
        assert browser.calls[3][1]["browserContextId"] == "CTX1"
        assert tabs[0].closed and pool.health()["contexts"] == 1

    def test_a_context_that_is_not_made_in_time_is_disposed_later(self, monkeypatch):
        monkeypatch.setattr(special_browser, "TAB_ANSWER_S", 0.05)

        class Slow(ContextBrowser):
            async def send(self, command):
                cmd = next(command)
                if cmd["method"] == "Target.createTarget":
                    await asyncio.sleep(0.1)
                return await ContextBrowser.send(self, _again(cmd, command))

        browser = Slow()
        pool = SpecialBrowser("_reader", 2)
        lease = Lease(tab=None, target_id="T0", died=asyncio.Event(), browser=browser)

        async def run():
            with pytest.raises(special_browser.TabNotAnswering):
                async with pool.context_tab(lease, "socks5://127.0.0.1:5555", "<-loopback>"):
                    pass
            await asyncio.sleep(0.2)

        asyncio.run(run())
        assert ("Target.disposeBrowserContext", {"browserContextId": "CTX1"}) in browser.calls
        assert pool._creating == 0


def _again(cmd: dict, command):
    def gen():
        answer = yield cmd
        try:
            command.send(answer)
        except StopIteration as stop:
            return stop.value
    return gen()




@pytest.mark.parametrize("addresses,expected_code", [
    (["127.0.0.1"], 2),
    (["93.184.215.14", "10.0.0.1"], 2),
    (["93.184.215.14"], 0),
])
def test_direct_relay_validates_all_addresses_and_connects_to_the_validated_ip(monkeypatch, addresses, expected_code):
    class Writer:
        def __init__(self):
            self.data = bytearray()
        def write(self, data):
            self.data.extend(data)
        async def drain(self):
            pass
    async def run():
        looked_up = []
        connected = []
        async def resolve(host, port, **kwargs):
            looked_up.append(host)
            return [(0, 0, 0, "", (address, port)) for address in addresses]
        async def connect(host, port):
            connected.append(host)
            return object(), Writer()
        async def pipe(*args):
            pass
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        monkeypatch.setattr(asyncio, "open_connection", connect)
        monkeypatch.setattr(tor_routes, "_pipe", pipe)
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x05\x01\x00\x05\x01\x00\x03" + _domain("rebind.example") + b"\x00\x50")
        reader.feed_eof()
        writer = Writer()
        await tor_routes.SocksRelay(None)._serve(reader, writer, [writer])
        assert looked_up == ["rebind.example"]
        assert writer.data[3] == expected_code
        assert connected == ([addresses[0]] if expected_code == 0 else [])
    asyncio.run(run())
