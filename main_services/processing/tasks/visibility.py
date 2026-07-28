"""Temporal visibility: the ``CollectionDataset`` search attribute.

Every workflow the pipeline starts — top-level submissions and child workflows
alike — carries the ``CollectionDataset`` keyword search attribute, so the admin
workflow browser can find all runs of a collection with one visibility query
(``CollectionDataset = 'testdata_1'``) instead of only the four workflow ids that
happen to embed the dataset name. Child workflows like ``HandleFolders-<hash>``
carry no dataset in their id; the attribute is what attributes them.

The attribute must exist on the cluster before any workflow start that sets it,
or the start is rejected. Registration is a one-time, idempotent cluster
operation done at worker startup (:func:`ensure_search_attributes`), so a fresh
``reset-docker.sh`` needs no manual step.
"""

import logging

from temporalio.client import Client
from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes

log = logging.getLogger(__name__)

COLLECTION_DATASET_ATTRIBUTE = "CollectionDataset"

COLLECTION_DATASET_KEY = SearchAttributeKey.for_keyword(COLLECTION_DATASET_ATTRIBUTE)


def dataset_search_attributes(collection_dataset: str) -> TypedSearchAttributes:
    """Search attributes tagging a workflow start with its dataset."""
    return TypedSearchAttributes(
        [SearchAttributePair(COLLECTION_DATASET_KEY, [collection_dataset])]
    )


async def ensure_search_attributes(client: Client) -> None:
    """Register the ``CollectionDataset`` keyword attribute on the default namespace.

    Idempotent: the cluster silently accepts re-registering an existing
    attribute, so every worker calls this on startup. A failure here is logged
    and swallowed — the worker can still run workflows that do not set the
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
