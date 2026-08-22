"""The batch shapes `whois_lookup` accepts, and the notes it sends back.

No network: the lookup itself is one library call, and what this suite protects is
everything around it — the coercion of whatever the model sent, the de-duplication, the
cap, and the corrective note that tells the model what happened to its call.
"""

import asyncio

import pytest

from whois_server import server as whois_srv


def _call(**kwargs):
    # This server is on the low-level SDK's FastMCP, whose `@tool` returns the plain
    # function rather than wrapping it — unlike the other three servers, where the tool is
    # an object carrying the callable as `.fn`. Accept either, so the day this server is
    # moved onto the same library the suite does not silently stop calling anything.
    tool = getattr(whois_srv.whois_lookup, "fn", whois_srv.whois_lookup)
    return asyncio.run(tool(**kwargs))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Every lookup resolves instantly and successfully, so a test that is about argument
    shapes cannot fail because a registry was slow."""

    async def one(domain):
        return whois_srv.WhoisLookupResponse(
            success=True,
            domain=domain,
            data=whois_srv.WhoisData(domain_name=domain),
            metadata=whois_srv.WhoisMetadata(
                lookup_time="", timeout_used=1, raw_available=True
            ),
        )

    monkeypatch.setattr(whois_srv, "_lookup_one", one)


class TestArgumentShapes:
    def test_a_real_list_is_looked_up_in_order(self):
        out = _call(domains=["a.example", "b.example"])
        assert [d.domain for d in out.domains] == ["a.example", "b.example"]

    def test_a_json_encoded_list_is_a_list(self):
        """XML-style tool-call parsers hand every parameter across as a string."""
        out = _call(domains='["a.example", "b.example"]')
        assert [d.domain for d in out.domains] == ["a.example", "b.example"]

    def test_a_bare_string_is_a_batch_of_one(self):
        assert [d.domain for d in _call(domains="a.example").domains] == ["a.example"]

    def test_the_retired_single_argument_still_works(self):
        """`domain` folds into `domains` rather than taking its own path, so a model that
        learned the single-domain shape keeps working."""
        assert [d.domain for d in _call(domain="a.example").domains] == ["a.example"]

    def test_a_url_becomes_a_hostname(self):
        out = _call(domains=["https://www.example.com/a/b?c=d"])
        assert [d.domain for d in out.domains] == ["example.com"]

    def test_no_domain_at_all_is_an_error_naming_the_parameter(self):
        out = _call(domains=[])
        assert out.success is False
        assert "domains" in (out.error or "")


class TestCorrectiveNotes:
    def test_a_repeat_is_run_once_and_said_so(self):
        """De-duplicating silently teaches the model nothing and it sends the same list
        again next turn."""
        out = _call(domains=["a.example", "A.example", "b.example"])
        assert [d.domain for d in out.domains] == ["a.example", "b.example"]
        assert "repeated domain" in (out.note or "")

    def test_a_url_and_its_bare_host_are_one_domain(self):
        out = _call(domains=["https://a.example/page", "a.example"])
        assert len(out.domains) == 1

    def test_the_surplus_over_the_cap_is_named(self, monkeypatch):
        monkeypatch.setattr(whois_srv, "MAX_DOMAINS", 2)
        out = _call(domains=["a.example", "b.example", "c.example"])
        assert len(out.domains) == 2
        assert "c.example" in (out.note or "")

    def test_an_ordinary_call_carries_no_note(self):
        assert _call(domains=["a.example"]).note is None


class TestFormatting:
    """`python-whois` returns a bare value where a registry holds only one."""

    def test_a_single_contact_is_still_a_list(self):
        """Left as a bare string this fails `WhoisData` validation, and a domain with one
        abuse contact answers with a validation error instead of its registration."""
        data = whois_srv.format_whois_data(
            {"emails": "abuse@example.com", "name_servers": "ns1.example.com"}
        )
        assert data.admin_email == ["abuse@example.com"]
        assert data.name_servers == ["ns1.example.com"]

    def test_a_list_is_left_as_a_list(self):
        data = whois_srv.format_whois_data({"emails": ["a@example.com", "b@example.com"]})
        assert data.admin_email == ["a@example.com", "b@example.com"]

    def test_an_absent_field_stays_absent(self):
        assert whois_srv.format_whois_data({}).admin_email is None
