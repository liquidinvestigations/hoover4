"""The Temporal connection of a process: the namespace and the key of the installation."""
import asyncio

import temporalio.client

from tasks import temporal_client


def test_compose_uses_the_namespace_default_without_a_key(monkeypatch):
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)
    monkeypatch.setenv("TEMPORAL_API_KEY", " ")
    assert temporal_client.namespace() == "default"
    assert temporal_client.api_key() is None
    assert temporal_client.http_headers() == {}


def test_a_zone_connects_with_its_namespace_and_key(monkeypatch):
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "zone-a")
    monkeypatch.setenv("TEMPORAL_API_KEY", "key-of-zone-a")
    seen = {}

    async def connect(target, **options):
        seen.update(options, target=target)
        return "client"
    monkeypatch.setattr(temporalio.client.Client, "connect", staticmethod(connect))
    assert asyncio.run(temporal_client.connect()) == "client"
    assert seen == {"target": "temporal:7233", "namespace": "zone-a", "api_key": "key-of-zone-a"}
    assert temporal_client.http_headers() == {"Authorization": "Bearer key-of-zone-a"}


def test_a_zone_key_without_attribute_rights_counts_the_attribute_as_registered():
    from temporalio.service import RPCError, RPCStatusCode

    from tasks import visibility

    class Operator:
        calls = 0

        async def add_search_attributes(self, *_args, **_kwargs):
            Operator.calls += 1
            raise RPCError("Request unauthorized.", RPCStatusCode.PERMISSION_DENIED, b"")

        list_search_attributes = add_search_attributes

    class FakeClient:
        operator_service = Operator()
    assert asyncio.run(visibility.ensure_search_attributes_ready(FakeClient(), timeout_seconds=1)) is True
    assert Operator.calls == 2
