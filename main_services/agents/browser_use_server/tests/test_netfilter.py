"""Tests for the browser-level network filter.

Two separate claims are checked here, because they failed separately:

1. the origins handed to playwright-mcp must be in the *one* form its `originOrHostGlob`
   compiles into a port-tolerant glob — the bare hostnames this code used to pass matched
   nothing, so the flag was inert on a network where every service has a port;
2. the PAC script must refuse every shape of internal target, including the ones that only
   ever arrive through a redirect and therefore never reach `urlcheck`.

(2) is checked structurally here. The end-to-end proof needs a real Chromium and the
network, and is recorded in the module docstring of `netfilter`: with the filter off, a
public redirect to `http://manticore:9308/sql?query=…` returned data; with it on, the same
redirect fails `ERR_PROXY_CONNECTION_FAILED`.
"""

import re

import pytest

from browser_use_server import netfilter
from browser_use_server.urlcheck import DENIED_HOSTS


def _origin_glob(origin: str) -> str:
    """playwright-mcp's `originOrHostGlob`, reimplemented so the test states the contract.

    Copied from `playwright-core/lib/coreBundle.js` (v0.0.79 of `@playwright/mcp`). If the
    sidecar is upgraded and this stops matching, the flag has gone inert again and this
    test is the thing that says so.
    """
    wildcard_port = re.match(r"^(https?://[^/:]+):\*$", origin)
    if wildcard_port:
        return f"{wildcard_port.group(1)}:*/**"
    return f"*://{origin}/**"


class TestBlockedOrigins:
    def test_every_host_becomes_a_port_tolerant_glob(self):
        origins = netfilter.blocked_origins("clickhouse;manticore").split(";")
        assert origins == [
            "http://clickhouse:*",
            "https://clickhouse:*",
            "http://manticore:*",
            "https://manticore:*",
        ]
        for origin in origins:
            assert _origin_glob(origin).endswith(":*/**"), origin

    def test_a_bare_hostname_would_not_have_matched_a_port(self):
        # The bug, pinned: `*` does not cross `/`, so the old glob missed every real URL.
        assert _origin_glob("manticore") == "*://manticore/**"
        assert not _glob_matches("*://manticore/**", "http://manticore:9308/sql")
        assert _glob_matches("http://manticore:*/**", "http://manticore:9308/sql")

    def test_blank_entries_and_ready_made_origins(self):
        assert netfilter.blocked_origins(" ; ;") == ""
        assert netfilter.blocked_origins("http://minio:9000") == "http://minio:9000"

    def test_default_list_is_urlchecks_list(self):
        hosts = set(netfilter.DEFAULT_BLOCKED_HOSTS.split(";"))
        assert hosts == set(DENIED_HOSTS)


def _glob_matches(glob: str, url: str) -> bool:
    """Playwright's glob semantics, reduced to what this test needs: `*` never crosses
    `/`, `**` does."""
    pattern = re.escape(glob).replace(r"\*\*", "\x00").replace(r"\*", "[^/]*")
    return re.fullmatch(pattern.replace("\x00", ".*"), url) is not None


class TestPacScript:
    @pytest.fixture
    def pac(self):
        return netfilter.pac_script()

    def test_single_label_hosts_are_blocked_without_a_list(self, pac):
        # The rule that keeps working when a new service joins the network.
        assert "isPlainHostName(host)" in pac

    def test_metadata_and_localhost_suffixes(self, pac):
        assert 'dnsDomainIs(host, ".internal")' in pac
        assert 'dnsDomainIs(host, ".localhost")' in pac

    @pytest.mark.parametrize(
        "net", ["10.0.0.0", "172.16.0.0", "192.168.0.0", "127.0.0.0", "169.254.0.0"]
    )
    def test_private_ranges_are_all_covered(self, pac, net):
        assert f'isInNet(ip, "{net}"' in pac

    def test_unresolvable_names_fail_closed(self, pac):
        assert "if (!ip) return BLOCK;" in pac

    def test_public_traffic_is_direct(self, pac):
        assert pac.rstrip().endswith('return "DIRECT";\n}')

    def test_blocked_requests_fail_fast_rather_than_hanging(self, pac):
        # A routable-but-dead address would hang until the navigation deadline; loopback
        # on a port nothing binds is refused immediately.
        assert 'var BLOCK = "PROXY 127.0.0.1:1";' in pac

    def test_data_url_is_what_chromium_expects(self):
        url = netfilter.pac_data_url()
        assert url.startswith("data:application/x-ns-proxy-autoconfig;base64,")
        import base64

        decoded = base64.b64decode(url.split(",", 1)[1]).decode("utf-8")
        assert decoded == netfilter.pac_script()
