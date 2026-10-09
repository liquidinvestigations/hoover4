"""The served descriptions of the three search tools, and the `queries` schema."""

from __future__ import annotations

import asyncio

from collection_search_server import tools_search
from collection_search_server.server import mcp

SEARCH_COLLECTIONS = """Search the user's documents. Leave out collection to search every collection of this chat. That is the default, and it is correct for most questions. Give collection only to narrow a search, with names from list_collections. A dataset is not a collection.

Give queries as a list of up to 12 forms of what you look for, for example the email address, the name in double quotes and the name with the surname first. Each row names the forms that found it in q, by number from 0. Do not make one call for each form.
Example: queries ["JoeBWilkinson@cs.com", "\\"Joe Wilkinson\\"", "\\"Wilkinson, Joe\\"", "JoeBWilkinson"]

Query rules:
- Words in a query must all occur: water testing
- | means either: water | sewage
- -word excludes a word: water -draft
- Double quotes find a phrase or a name: "Joe Wilkinson"
- OR, AND and NOT are ordinary words. Use | and -word. The search reads OR as | and NOT x as -x, and says so in query_notes.
- from: and to: are not fields. The search drops them, keeps the word after them, and says so in query_notes.
- An email address works as typed.
- Proximity finds nearby words: "water pollution"~10
- Quorum requires some words: "water pollution plant"/2
- An alternative works inside a phrase, proximity or quorum: "(water | sewage) plant"
- NOTNEAR excludes nearby words: water NOTNEAR/5 testing
- ? matches one character: dasovi?h
- % matches zero or one character: dasovic%
- << requires word order: skilling << resigned
- Word forms do not match automatically. Use contract | contracts or contract*.
- word_counts gives the folded word and its checked document count over the searched tables.
- suggestions gives indexed close words with checked counts. Use one only for the intended name.

Each row gives file_hash, path, collection and known size in bytes. Copy file_hash from a row to read_documents. Never write a hash yourself. When the result has more, give that value to read_more to get the other rows.

Use facet_filters with value text or term ids. An empty query lists every filter match. The result reports each applied filter and unknown value. Dates are epoch seconds. size_min and size_max are in bytes. For PDFs by size, use file_types: ["pdf"] and sort by file_size. For email between two people, use email_from and email_to with their addresses. For a location, use ner_loc: ["Chicago"]. language accepts a code or English name. red_flags accepts a category identifier or title."""

SEARCH_PASSAGES = "Search the text passages of the user's documents by keywords and by meaning together. Use it for a question in plain words, when you do not know the words that the documents use. Leave out collection to search every collection of this chat. Give up to 12 queries in one call. Each row names the forms that found it in q, by number from 0. Copy file_hash from a row to read_documents. For an exact name, address or phrase, use search_collections."

LIST_COLLECTIONS = "List the collections of this chat and the datasets in each. You do not need it before a search, because a search with no collection covers every collection. A dataset name, for example tables/ehudx, is not a collection name. Give the collection name, tables."


def served() -> dict:
    return asyncio.run(mcp.get_tools())


def test_the_served_descriptions_are_the_drafted_texts():
    tools = served()
    assert tools["search_collections"].description == SEARCH_COLLECTIONS
    assert tools["search_passages"].description == SEARCH_PASSAGES
    assert tools["list_collections"].description == LIST_COLLECTIONS
    assert '"\\"Joe Wilkinson\\""' in tools["search_collections"].description


def test_search_collections_takes_a_list_of_up_to_12_queries():
    schema = served()["search_collections"].parameters["properties"]["queries"]
    assert schema["default"] is None
    assert {"type": "array", "items": {"type": "string"}, "maxItems": 12} in schema["anyOf"]
    assert {"type": "null"} in schema["anyOf"]
    assert tools_search.SearchCollectionsRequest.model_fields["queries"].metadata


def test_both_search_texts_say_up_to_12():
    assert "up to 12" in tools_search.SEARCH_COLLECTIONS_TEXT
    assert "up to 12" in tools_search.SEARCH_PASSAGES_TEXT
