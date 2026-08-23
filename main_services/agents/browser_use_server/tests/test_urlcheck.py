"""Tests for the URL admission control.

This is the security boundary of the server (an LLM chooses the URLs and the container
sits inside the network where ClickHouse and Temporal answer unauthenticated requests)
so it is tested far harder than the rest of the code. Everything here is offline: the
cases that would need DNS use literal addresses or the documented exemption.
"""

import pytest

from browser_use_server.urlcheck import UrlNotAllowed, check_tool_arguments, check_url


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
            "clickhouse", "manticore", "temporal", "redis", "minio-s3", "garage",
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


class TestToolArgumentGuard:
    """The boundary in front of the whole Playwright surface.

    `browse_page` was the only navigating tool when this module was written; the router
    now forwards two dozen, and every one of them is checked here *before* the call
    reaches the sidecar. The sidecar's own `--blocked-origins` is the second line.
    Playwright documents it as not being a security boundary.
    """

    def test_an_internal_host_is_refused_for_browser_navigate(self):
        with pytest.raises(UrlNotAllowed, match="internal service"):
            check_tool_arguments("browser_navigate", {"url": "http://clickhouse:8123/"})

    def test_a_file_scheme_is_refused(self):
        with pytest.raises(UrlNotAllowed):
            check_tool_arguments("browser_navigate", {"url": "file:///etc/passwd"})

    @pytest.mark.parametrize(
        "url", ["data:text/html,<script>x</script>", "chrome://settings", "javascript:alert(1)"]
    )
    def test_non_http_schemes_are_refused(self, url):
        with pytest.raises(UrlNotAllowed):
            check_tool_arguments("browser_navigate", {"url": url})

    def test_about_blank_is_allowed_because_playwright_uses_it(self):
        check_tool_arguments("browser_navigate", {"url": "about:blank"})

    def test_a_url_in_a_list_argument_is_checked(self):
        with pytest.raises(UrlNotAllowed):
            check_tool_arguments("browser_tabs", {"urls": ["https://example.com", "http://redis:6379"]})

    def test_typed_text_that_looks_like_a_url_is_not_a_navigation(self):
        """`browser_type` puts text in a field. Refusing it would break filling in a
        form that legitimately mentions an internal hostname."""
        check_tool_arguments("browser_type", {"text": "http://clickhouse:8123", "ref": "e1"})

    def test_a_tool_with_no_url_argument_passes_through(self):
        check_tool_arguments("browser_snapshot", {})
        check_tool_arguments("browser_click", {"ref": "e12", "element": "Submit button"})

    def test_a_public_url_passes(self, monkeypatch):
        monkeypatch.setenv("BROWSER_SKIP_DNS_CHECK", "1")
        check_tool_arguments("browser_navigate", {"url": "https://example.com/page"})

    def test_an_empty_url_is_ignored_rather_than_refused(self):
        check_tool_arguments("browser_navigate", {"url": ""})
