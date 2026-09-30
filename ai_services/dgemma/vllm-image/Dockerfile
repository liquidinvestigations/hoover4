# This file builds the image of hoover4-vllm from the djev-spark build and the local patches.
#
# UPSTREAM_IMAGE is the image that deploy.py builds from vllm_build_repo at
# vllm_build_ref. That build and its checkouts stay unchanged. This file applies the
# patch files below to the vLLM package of that image.
#
# With parser-arguments.patch, the tool call parser sends the arguments of a call once, at
# the end of the call, when the parser converts the model's own argument syntax to
# JSON. check_parser.py tests it.

ARG UPSTREAM_IMAGE
FROM ${UPSTREAM_IMAGE}

COPY parser-arguments.patch /tmp/hoover4-patches/
RUN site="$(python3 -c 'import os, vllm; print(os.path.dirname(os.path.dirname(vllm.__file__)))')" \
    && patch --forward --batch --no-backup-if-mismatch -p1 -d "$site" < /tmp/hoover4-patches/parser-arguments.patch \
    && rm -f "$site"/vllm/parser/engine/__pycache__/parser_engine.*.pyc \
    && python3 -m py_compile "$site"/vllm/parser/engine/parser_engine.py \
    && grep -q "hoover4 patch" "$site"/vllm/parser/engine/parser_engine.py \
    && rm -rf /tmp/hoover4-patches
