# Hermes matcher

`fuzzy_match.py` and `escape_drift_autocorrect.py` are copies from the Hermes Agent
repository (`github.com/NousResearch/hermes-agent`), commit
`9e01b44dd23978f9ff40b7837467f3a9f1582130`, path `tools/`. Copyright (c) 2025 Nous
Research, under the MIT licence in [LICENSE](LICENSE).

The only change is the import path of `escape_drift_autocorrect` in `fuzzy_match.py`. The
text of the upstream messages stays as written upstream. `tasks/P_workspace/mutations.py`
calls `fuzzy_find_and_replace` and rewrites the upstream tool names in its messages.
The retained upstream tests are in `tests/unit/test_hermes_fuzzy_match.py`.
