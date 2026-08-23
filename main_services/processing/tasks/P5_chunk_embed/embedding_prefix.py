"""The e5 prefix convention, keyed off the probed serving model id.

**This is the indexing-side half of the one prefix function.** The search-side half is
`main_services/agents/agent_common/agent_common/embeddings.py::embedding_input`; the
duplication is deliberate (same pattern as `extracted_by` in `tasks/text_sources.py` vs
`website/common/src/document_sources.rs`) because the processing image and the agents
images share no package. The two implementations must agree exactly: a passage embedded
with the query convention (or vice versa) degrades retrieval silently and nothing will
ever alert you.

The convention keys off the model id recorded in `server_settings`
(`embeddings_serving_model`, written by `main.py probe-embeddings`), which is the probed
truth rather than the configured `embeddings_model` from the ini. Note for anyone reverting to
`e5-large-instruct`: its convention is DIFFERENT (bare passages; queries wrapped as
`Instruct: {task}\\nQuery: {text}`, applied by the server from `task_description`), which
is exactly why this is a function of the model id and not a module-level constant.
"""

#: The task description the server wraps around a QUERY for instruct models. Must match
#: `QUERY_TASK` in `agent_common/embeddings.py`.
QUERY_TASK = "Given a search query, retrieve relevant passages from a document collection"


def embedding_input(model_id: str, kind: str, text: str) -> tuple[str, str | None]:
    """Turn `text` into what the embeddings endpoint should receive.

    `kind` is `"passage"` (a stored chunk, which is what this stage embeds) or `"query"` (a
    search query, which is the collection-search server's half of the convention). Returns
    `(text_to_send, task_description)`; `task_description` is set only for instruct
    models, whose query template the server applies.

    * `intfloat/multilingual-e5-*` and the other non-instruct e5 models:
      `passage: ` / `query: ` prepended here.
    * `*-e5-*-instruct`: passages bare; queries bare plus the task description.
    * Anything else raises, a model whose convention we do not know gets no vectors
      rather than wrong ones.
    """
    name = (model_id or "").lower()
    if kind not in ("passage", "query"):
        raise ValueError(f"kind must be 'passage' or 'query', got {kind!r}")
    if "e5" not in name:
        raise ValueError(
            f"no embedding prefix convention is known for model {model_id!r}; "
            "add it to embedding_input in BOTH runtimes (see module docstring)"
        )
    if "instruct" in name:
        if kind == "query":
            return text, QUERY_TASK
        return text, None
    prefix = "passage: " if kind == "passage" else "query: "
    return prefix + text, None
