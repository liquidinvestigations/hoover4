"""The served descriptions of the three search tools, and the `queries` schema."""

from __future__ import annotations

import asyncio

from collection_search_server import tools_search
from collection_search_server.server import mcp

SEARCH_COLLECTIONS = """Search the user's documents. Leave out collectionname to search every collection of this chat. That is the default, and it is correct for most questions. Give collectionname only to narrow a search, with names from list_collections. A dataset is not a collection.

Give queries as a list of up to 8 forms of what you look for, for example the email address, the name in double quotes and the name with the surname first. Each row names the queries that found it. Do not make one call for each form.
Example: queries ["JoeBWilkinson@cs.com", "\\"Joe Wilkinson\\"", "\\"Wilkinson, Joe\\"", "JoeBWilkinson"]

Query rules:
- Words in a query must all occur: water testing
- | means either: water | sewage
- -word excludes a word: water -draft
- Double quotes find a phrase or a name: "Joe Wilkinson"
- OR, AND and NOT are ordinary words. Use | and -word. The search reads OR as | and NOT x as -x, and says so in query_notes.
- An email address works as typed.

Each row gives file_hash, path and collectionname. Copy file_hash from a row to read_documents. Never write a hash yourself. When the result has a continuation, call read_more to get the other rows.

Set a filter only when the user asks for it. Dates are epoch seconds. size_min and size_max are in bytes. A facet_filters value is a term id from a facet count or search_facet_values."""

SEARCH_PASSAGES = "Search the text passages of the user's documents by keywords and by meaning together. Use it for a question in plain words, when you do not know the words that the documents use. Leave out collectionname to search every collection of this chat. Give up to 8 queries in one call. Each hit names the queries that found it. For an exact name, address or phrase, use search_collections."

LIST_COLLECTIONS = "List the collections of this chat and the datasets in each. You do not need it before a search, because a search with no collectionname covers every collection. A dataset name, for example tables/ehudx, is not a collection name. Give the collection name, tables."


def served() -> dict:
    return asyncio.run(mcp.get_tools())


def test_the_served_descriptions_are_the_drafted_texts():
    tools = served()
    assert tools["search_collections"].description == SEARCH_COLLECTIONS
    assert tools["search_passages"].description == SEARCH_PASSAGES
    assert tools["list_collections"].description == LIST_COLLECTIONS
    assert '"\\"Joe Wilkinson\\""' in tools["search_collections"].description


def test_search_collections_takes_a_list_of_up_to_8_queries():
    schema = served()["search_collections"].parameters["properties"]["queries"]
    assert schema["default"] is None
    assert {"type": "array", "items": {"type": "string"}, "maxItems": 8} in schema["anyOf"]
    assert {"type": "null"} in schema["anyOf"]
    assert tools_search.SearchCollectionsRequest.model_fields["queries"].metadata
