#!/usr/bin/env python3
"""The list price of every model this repository has been worked on.

    prices.py            print the table and what it does not cover

Read from each provider's own documentation on 2026-09-11. Every row names the page it
came from. A reseller's consolidated list is a secondary source and is used only to check
that no model was missed.

Prices are US dollars per million tokens, at the standard tier and the short-context rate.

    input        an uncached prompt token
    cache_write  a prompt token written into the cache
    cache_read   a prompt token served from the cache
    output       a generated token, reasoning tokens included

WHAT THIS TABLE DOES NOT COVER

**The long-context tier.** OpenAI charges 2x input and 1.5x output for a request over
272,000 tokens. xAI charges a higher rate over 200,000 and does not list it on the model
page. The measured peak prompt of an implementation pass here is 193,565 at p50 and
308,790 at p90, so a p90 pass crosses the OpenAI boundary and every Grok pass over 200,000
crosses the xAI one. A cost read from this table is therefore a floor for a large pass.

**A subscription.** Claude Code, Codex, Kimi Code and Cursor are used here through
subscriptions, not through the API. These rates are what the same tokens would cost at the
API meter. They are the only per-model figure that can be compared across providers, and
that comparison is what the estimate needs.

**Cursor's own models.** `composer-2.5` has no published token price. Cursor bills it in
credits, so no row exists for it here.
"""

#: (input, cache_write, cache_read, output) in dollars per million tokens.
#: The fourth column of the key names the page each row was read from.
PRICES = {
    # https://platform.claude.com/docs/en/about-claude/pricing
    "claude-opus-5": (5.00, 6.25, 0.50, 25.00),
    "claude-opus-4.8": (5.00, 6.25, 0.50, 25.00),
    "claude-sonnet-5": (2.00, 2.50, 0.20, 10.00),
    "claude-haiku-4-5": (1.00, 1.25, 0.10, 5.00),
    "claude-fable-5-1": (10.00, 12.50, 0.25, 50.00),
    # https://developers.openai.com/api/docs/pricing
    "gpt-6-astra": (10.00, 12.50, 1.00, 50.00),
    "gpt-5.6-sol": (4.00, 5.00, 0.40, 20.00),
    "gpt-5.6-terra": (2.00, 2.50, 0.20, 12.00),
    "gpt-5.6-luna": (0.20, 0.25, 0.02, 1.20),
    # https://platform.kimi.ai/docs/pricing/chat
    "kimi-code/k3": (3.00, 3.00, 0.30, 15.00),
    "kimi-code/k3-256k": (3.00, 3.00, 0.30, 15.00),
    "kimi-code/k2.7-code": (0.95, 0.95, 0.19, 4.00),
    # https://docs.x.ai/developers/models/grok-4.6
    "grok-4.6": (2.00, 2.00, 0.50, 6.00),
}

#: A model that has been used here and has no published token price.
UNPRICED = {
    "grok-4.5": "superseded, and no longer listed on the xAI model pages",
    "composer-2.5": "a Cursor model, billed in credits with no token rate published",
}

#: Where a harness's name for a model differs from the provider's own.
ALIASES = {
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
    "k3": "kimi-code/k3",
    "k3-256k": "kimi-code/k3-256k",
}

#: The tier a model sits in, which is what a plan reaches for when it has not yet chosen
#: one. Read from the price of an implementation pass rather than from the provider's own
#: marketing name for the tier.
TIERS = {
    "frontier": ("claude-fable-5-1", "gpt-6-astra"),
    "workhorse": ("claude-opus-5", "gpt-5.6-sol"),
    "value": ("claude-sonnet-5", "gpt-5.6-terra", "kimi-code/k3", "grok-4.6"),
    "cheap": ("claude-haiku-4-5", "gpt-5.6-luna", "kimi-code/k2.7-code"),
}


def price_of(model):
    """Return the four rates for a model, or None when it has no published price."""
    if not model:
        return None
    name = ALIASES.get(model, model)
    return PRICES.get(name)


def tier_of(model):
    name = ALIASES.get(model or "", model)
    for tier, members in TIERS.items():
        if name in members:
            return tier
    return None


def cost_of(record):
    """Dollars for one pass, from its recorded token counts at list price.

    Returns None when the model has no published price or the harness recorded no token
    counts. A None is dropped from a distribution rather than counted as zero.
    """
    rates = price_of(record.get("model"))
    if rates is None:
        return None
    tokens = (record.get("input_tokens"), record.get("output_tokens"),
              record.get("cache_read"), record.get("cache_write"))
    if all(t is None for t in tokens):
        return None
    rate_in, rate_write, rate_read, rate_out = rates
    return ((record.get("input_tokens") or 0) * rate_in
            + (record.get("cache_write") or 0) * rate_write
            + (record.get("cache_read") or 0) * rate_read
            + (record.get("output_tokens") or 0) * rate_out) / 1e6


if __name__ == "__main__":
    print(f"{'model':<26} {'tier':<10} {'input':>7} {'cw':>7} {'cr':>7} {'output':>7}")
    for model, rates in PRICES.items():
        print(f"{model:<26} {tier_of(model) or '-':<10} "
              + " ".join(f"{r:7.2f}" for r in rates))
    print()
    for model, why in UNPRICED.items():
        print(f"{model:<26} no published price: {why}")
