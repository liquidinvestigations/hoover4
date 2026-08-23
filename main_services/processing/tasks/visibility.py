"""Temporal visibility: the ``CollectionDataset`` search attribute.

Every workflow the pipeline starts (top-level submissions and child workflows
alike) carries the ``CollectionDataset`` keyword search attribute, so the admin
workflow browser can find all runs of a collection with one visibility query
(``CollectionDataset = 'testdata_1'``) instead of only the four workflow ids that
happen to embed the dataset name. Child workflows like ``HandleFolders-<hash>``
carry no dataset in their id; the attribute is what attributes them.

The attribute must exist on the cluster before any workflow start that sets it,
or the start is rejected with ``search attribute CollectionDataset is not
defined``. Registration is a one-time, idempotent cluster operation done at
worker startup (:func:`ensure_search_attributes`).

**That is not sufficient on its own**, and a fresh ``./deploy --reset`` is
exactly where it shows: the CLI (``add-disk-dataset``) can reach Temporal before
the worker has finished registering, and registration is not instant even once
issued -- Temporal has to push the mapping to Elasticsearch. Any process that
*starts* a workflow must therefore call :func:`ensure_search_attributes_ready`
and wait for the attribute to actually be listed, not merely assume the worker
got there first.
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes

log = logging.getLogger(__name__)

COLLECTION_DATASET_ATTRIBUTE = "CollectionDataset"

COLLECTION_DATASET_KEY = SearchAttributeKey.for_keyword(COLLECTION_DATASET_ATTRIBUTE)


def dataset_search_attributes(collection_dataset: str) -> TypedSearchAttributes:
    """Search attributes tagging a workflow start with its dataset."""
    return TypedSearchAttributes(
        [SearchAttributePair(COLLECTION_DATASET_KEY, collection_dataset)]
    )


async def ensure_search_attributes(client: Client) -> None:
    """Register the ``CollectionDataset`` keyword attribute on the default namespace.

    Idempotent: the cluster silently accepts re-registering an existing
    attribute, so every worker calls this on startup. A failure here is logged
    and swallowed. The worker can still run workflows that do not set the
    attribute, and the admin page keeps its workflow-id fallback clause.
    """
    from temporalio.api.enums.v1 import IndexedValueType
    from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest

    try:
        await client.operator_service.add_search_attributes(
            AddSearchAttributesRequest(
                namespace="default",
                search_attributes={
                    COLLECTION_DATASET_ATTRIBUTE: IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
                },
            )
        )
        log.info("Temporal search attribute %s registered", COLLECTION_DATASET_ATTRIBUTE)
    except Exception as e:  # noqa: BLE001 - bootstrap must not kill the worker
        log.warning("Could not register Temporal search attribute %s: %s", COLLECTION_DATASET_ATTRIBUTE, e)


async def _attribute_is_listed(client: Client) -> bool:
    from temporalio.api.operatorservice.v1 import ListSearchAttributesRequest

    resp = await client.operator_service.list_search_attributes(
        ListSearchAttributesRequest(namespace="default")
    )
    return COLLECTION_DATASET_ATTRIBUTE in resp.custom_attributes


async def ensure_search_attributes_ready(client: Client, timeout_seconds: float = 120.0) -> bool:
    """Register the attribute and wait until the cluster actually lists it.

    Unlike :func:`ensure_search_attributes`, this is for the *submitting* side,
    where getting it wrong is fatal rather than cosmetic: starting a workflow
    with an unregistered search attribute is rejected outright, which is how a
    fresh ``./deploy --reset && ./verify-stack.sh`` used to die five seconds in
    with ``search attribute CollectionDataset is not defined``.

    Returns whether the attribute is usable. Never raises -- the caller gets a
    clear failure from the workflow start itself if this could not be satisfied.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    await ensure_search_attributes(client)
    while True:
        try:
            if await _attribute_is_listed(client):
                return True
        except Exception as e:  # noqa: BLE001 - keep polling through transient RPC errors
            log.debug("list_search_attributes failed while waiting: %s", e)
        if asyncio.get_event_loop().time() >= deadline:
            log.warning(
                "Temporal search attribute %s still not listed after %.0fs",
                COLLECTION_DATASET_ATTRIBUTE, timeout_seconds,
            )
            return False
        await asyncio.sleep(2)
        # Re-issue: a registration sent while the cluster was still starting up
        # can be accepted and then lost behind an Elasticsearch mapping error.
        await ensure_search_attributes(client)


def _is_missing_attribute_error(exc: BaseException) -> bool:
    return COLLECTION_DATASET_ATTRIBUTE in str(exc) and "not defined" in str(exc)


async def start_with_attribute_retry(coro_factory, *, timeout_seconds: float = 180.0):
    """Await ``coro_factory()``, retrying while Temporal rejects the search attribute.

    Registering the attribute is NOT enough, which is the subtlety that made
    this fail twice after it looked fixed: ``list_search_attributes`` (operator
    service) reports it immediately, while the **frontend service caches its own
    copy** and keeps rejecting starts until that cache refreshes. So there is a
    window where the attribute provably exists and starting a workflow that uses
    it still fails with "search attribute CollectionDataset is not defined".

    Polling for readiness cannot close that window -- only retrying the start
    can. Takes a factory rather than a coroutine because a coroutine cannot be
    awaited twice.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001 - narrowed immediately below
            if not _is_missing_attribute_error(e):
                raise
            if asyncio.get_event_loop().time() >= deadline:
                log.error(
                    "Temporal still rejects %s after %.0fs and %d attempts",
                    COLLECTION_DATASET_ATTRIBUTE, timeout_seconds, attempt,
                )
                raise
            log.info(
                "Temporal frontend has not picked up %s yet (attempt %d), retrying",
                COLLECTION_DATASET_ATTRIBUTE, attempt,
            )
            await asyncio.sleep(3)
