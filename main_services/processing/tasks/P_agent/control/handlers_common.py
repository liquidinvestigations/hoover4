"""Text helpers of the built-in policy handlers. A handler module imports this module and no
other handler module."""

from __future__ import annotations

from typing import Mapping


def read_urls(fact) -> list[str]:
    """The addresses that one `read_page` call requested."""
    args = fact.args if isinstance(fact.args, Mapping) else {}
    urls = args.get("urls") or args.get("url") or []
    return [urls] if isinstance(urls, str) else [u for u in urls if isinstance(u, str)]
