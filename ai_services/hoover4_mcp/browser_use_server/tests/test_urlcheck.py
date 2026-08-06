"""Tests for the URL admission control.

This is the security boundary of the server — an LLM chooses the URLs and the container
sits inside the network where ClickHouse and Temporal answer unauthenticated requests —
so it is tested far harder than the rest of the code. Everything here is offline: the
cases that would need DNS use literal addresses or the documented escape hatch.
"""

import pytest

from browser_use_server.urlcheck import UrlNotAllowed, check_url


class TestSchemes:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "file://localhost/etc/shadow",
            "chrome://settings",
            "chrome-devtools://devtools/bundled/inspector.html",
            "data:text/html,<script>fetch('http://clickhouse:8123')</script>",
            "ftp://example.com/x",
            "javascript:alert(1)",
            "view-source:http://clickhouse:8123",
        ],
    )
    def test_non_http_schemes_are_refused(self, url):
        with pytest.raises(UrlNotAllowed):
            check_url(url)

    def test_https_and_http_are_the_only_ones_allowed(self):
        # Uses a literal public address so the test needs no DNS.
        assert check_url("https://93.184.216.34/")
        assert check_url("http://93.184.216.34/")


class TestInternalServices:
    @pytest.mark.parametrize(
        "host",
        [
            "clickhouse", "manticore", "temporal", "redis", "minio-s3",
            "hoover4-vllm", "hoover4-ai-server", "hoover4-mcp-collections",
            "localhost",
        ],
    )
    def test_named_stack_services_are_refused(self, host):
        """These resolve inside the podman network and answer without authentication."""
        with pytest.raises(UrlNotAllowed, match="internal service"):
            check_url(f"http://{host}:8123/")

    def test_the_dot_internal_suffix_is_refused(self):
        with pytest.raises(UrlNotAllowed, match="internal service"):
            check_url("http://metadata.google.internal/computeMetadata/v1/")


class TestAddressRanges:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",       # loopback
            "127.1.2.3",       # the whole /8, not just .1
            "0.0.0.0",         # unspecified
            "10.0.0.5",        # RFC1918
            "172.16.4.4",      # RFC1918
            "192.168.1.1",     # RFC1918
            "169.254.169.254", # cloud metadata, link-local
            "224.0.0.1",       # multicast
            "240.0.0.1",       # reserved
            "[::1]",           # IPv6 loopback
            "[fe80::1]",       # IPv6 link-local
            "[fc00::1]",       # IPv6 unique-local
        ],
    )
    def test_non_public_literals_are_refused(self, address):
        with pytest.raises(UrlNotAllowed, match="non-public|internal"):
            check_url(f"http://{address}:8123/")

    def test_a_public_literal_is_allowed(self):
        assert check_url("https://93.184.216.34/page")

    def test_a_public_ipv6_literal_is_allowed(self):
        assert check_url("https://[2606:2800:220:1:248:1893:25c8:1946]/")


class TestResolution:
    def test_a_public_name_with_a_private_record_is_refused(self):
        """The classic SSRF bypass: a name anyone can register that points at 127.0.0.1.

        The check resolves and inspects every address, so this is caught even though the
        hostname itself is on no deny-list.
        """
        import socket

        try:
            socket.getaddrinfo("localtest.me", None)
        except socket.gaierror:
            pytest.skip("no DNS in this environment")
        with pytest.raises(UrlNotAllowed, match="non-public"):
            check_url("http://localtest.me:8123/")

    def test_an_unresolvable_host_is_refused_rather_than_attempted(self):
        with pytest.raises(UrlNotAllowed, match="does not resolve"):
            check_url("http://no-such-host.invalid/")


class TestMalformed:
    @pytest.mark.parametrize("url", ["", "   ", "not a url", "http://", "https://"])
    def test_junk_is_refused(self, url):
        with pytest.raises(UrlNotAllowed):
            check_url(url)
