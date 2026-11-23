"""Shared outbound pacing with process state. See agent_common/outbound_pacing.py.

The Redis scripts get the same cases in the stack check of the plan that introduced them.
"""

import asyncio
import email.utils
import time

import pytest

from agent_common import outbound_pacing as pacing

INTERVAL = 0.3


@pytest.fixture(autouse=True)
def process_state(monkeypatch):
    def no_store():
        raise RuntimeError("tests use process state")

    monkeypatch.setenv("OUTBOUND_INTERVAL_SECONDS", str(INTERVAL))
    monkeypatch.delenv("OUTBOUND_POLICY_INTERVALS", raising=False)
    monkeypatch.setattr(pacing, "_redis", no_store)
    monkeypatch.setattr(pacing, "_LOCAL", {})


def run(coroutine):
    return asyncio.run(coroutine)


def later(seconds=5.0):
    return time.monotonic() + seconds


def test_the_key_is_the_host_or_its_provider_group():
    assert pacing.policy_key("https://en.wikipedia.org/wiki/Ada") == "wikimedia"
    assert pacing.policy_key("https://www.wikidata.org/wiki/Q1") == "wikimedia"
    assert pacing.policy_key("https://en.wikipedia.org/w/api.php?q=x") == "wikimedia-api"
    assert pacing.policy_key("https://www.wikidata.org/w/api.php") == "wikimedia-api"
    assert pacing.policy_key("https://en.wikipedia.org/api/rest_v1/page") == "wikimedia-api"
    assert pacing.policy_key("https://web.archive.org/web/2020/x") == "archive"
    assert pacing.policy_key("https://WWW.Example.org./a") == "example.org"
    assert pacing.policy_key("news.example.org") == "news.example.org"


def test_starts_of_one_key_are_one_interval_apart_and_other_keys_start_at_once():
    async def scenario():
        first = await pacing.admit("https://a.example/1", later())
        other = await pacing.admit("https://b.example/1", later())
        started = time.monotonic()
        second = await pacing.admit("https://a.example/2", later())
        return first, other, second, time.monotonic() - started

    first, other, second, elapsed = run(scenario())
    assert first == 0 and other == 0
    assert second == pytest.approx(INTERVAL, abs=0.05)
    assert elapsed >= INTERVAL - 0.05


def test_wikipedia_and_wikidata_share_one_permit_sequence():
    async def scenario():
        await pacing.admit("https://en.wikipedia.org/w/api.php", later())
        return await pacing.admit("https://www.wikidata.org/w/api.php?action=x", later())

    assert run(scenario()) == pytest.approx(INTERVAL, abs=0.05)


def test_an_idle_key_gives_one_immediate_start_and_no_burst():
    async def scenario():
        await pacing.admit("https://a.example/1", later())
        await asyncio.sleep(INTERVAL * 3)
        first = await pacing.admit("https://a.example/2", later())
        second = await pacing.admit("https://a.example/3", later())
        return first, second

    first, second = run(scenario())
    assert first == 0
    assert second == pytest.approx(INTERVAL, abs=0.05)


def test_a_permit_after_the_deadline_defers_and_reserves_nothing():
    async def scenario():
        await pacing.admit("https://a.example/1", later())
        with pytest.raises(pacing.Deferred) as caught:
            await pacing.admit("https://a.example/2", time.monotonic() + INTERVAL / 3)
        assert caught.value.next_at > time.time()
        waited = await pacing.admit("https://a.example/3", later())
        return caught.value, waited

    deferred, waited = run(scenario())
    assert deferred.key == "a.example" and deferred.reason == "pacing"
    assert str(deferred).startswith("deferred: a.example")
    assert waited <= INTERVAL


def test_a_429_with_retry_after_sets_a_provider_cooldown():
    async def scenario():
        await pacing.admit("https://a.example/1", later())
        seconds = await pacing.record("https://a.example/1", 429, "2")
        with pytest.raises(pacing.Deferred) as caught:
            await pacing.admit("https://a.example/2", later(1.0))
        return seconds, caught.value

    seconds, deferred = run(scenario())
    assert seconds == 2.0
    assert deferred.reason == "provider cooldown" and deferred.wait_s > 1.5


def test_retry_after_reads_seconds_and_an_http_date():
    assert pacing.retry_after_seconds("120") == 120.0
    date = email.utils.formatdate(time.time() + 60, usegmt=True)
    assert 55 <= pacing.retry_after_seconds(date) <= 61
    assert pacing.retry_after_seconds("soon") is None
    assert pacing.retry_after_seconds(None) is None


def test_a_503_without_retry_after_backs_off_and_a_success_resets_it():
    async def scenario():
        one = await pacing.record("https://a.example/1", 503)
        two = await pacing.record("https://a.example/1", 503)
        await pacing.record("https://a.example/1", 200)
        three = await pacing.record("https://a.example/1", 503)
        return one, two, three

    one, two, three = run(scenario())
    assert INTERVAL * 0.8 <= one <= INTERVAL * 1.2
    assert INTERVAL * 1.6 <= two <= INTERVAL * 2.4
    assert INTERVAL * 0.8 <= three <= INTERVAL * 1.2
    assert pacing.backoff_seconds(50, 6.0) <= pacing.BACKOFF_MAX_S * 1.2


def test_a_redirect_to_another_remote_charges_its_key():
    async def scenario():
        await pacing.follow("https://a.example/1", "https://b.example/landing")
        await pacing.follow("https://a.example/1", "https://a.example/other")
        to_b = await pacing.admit("https://b.example/2", later())
        to_a = await pacing.admit("https://a.example/2", later())
        return to_b, to_a

    to_b, to_a = run(scenario())
    assert to_b == pytest.approx(INTERVAL, abs=0.05)
    assert to_a == 0


def test_a_key_can_have_its_own_interval(monkeypatch):
    monkeypatch.setenv("OUTBOUND_POLICY_INTERVALS", "wikimedia=0.6, archive=0.1")
    assert pacing.interval_of("wikimedia") == 0.6
    assert pacing.interval_of("archive") == 0.1
    assert pacing.interval_of("example.org") == INTERVAL


def test_a_page_read_cooldown_does_not_stop_the_api_requests():
    async def scenario():
        await pacing.record("https://en.wikipedia.org/wiki/Ada", 429, "30")
        return await pacing.admit("https://en.wikipedia.org/w/api.php", later(1.0))

    assert run(scenario()) == 0
