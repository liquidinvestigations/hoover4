# This file builds the image of hoover4-vllm from a vLLM release image, the support files
# of djev-spark, the djev structured server and the local patches.
#
# The base is the vLLM release image vllm/vllm-openai:VLLM_BASE_RELEASE, which deploy.py
# pins. A release tag stays on Docker Hub. A nightly tag is deleted after about a week, so
# the build does not use one.
#
# The support files come from vllm_build_repo at vllm_build_ref: the CUDA header links,
# the worker memory cap, the entrypoint, the test pages and the image check. The
# Dockerfile of that repository is not used, because it pins a nightly base.
#
# diffusion-gemma-stack.patch adds the DiffusionGemma changes that the release does not
# have yet: the skip of the last self-conditioning step (vllm-project/vllm#58221), engine
# samples (vllm-project/vllm#58438) and the load-adaptive canvas width. The patch is made
# against that release, and the build stops when the base reports another version or a
# patch does not apply.
#
# With parser-arguments.patch, the tool call parser sends the arguments of a call once, at
# the end of the call, when the parser converts the model's own argument syntax to
# JSON. check_parser.py tests it.

ARG VLLM_BASE_RELEASE

FROM alpine/git:latest AS sources
ARG VLLM_BUILD_REPO
ARG VLLM_BUILD_REF
# The commit of the structured server that djev-spark at VLLM_BUILD_REF pins.
ARG DJEV_REPO=https://github.com/mmastrac/djev.git
ARG DJEV_REF=9a67e54
RUN git clone --quiet "${VLLM_BUILD_REPO}" /djev-spark \
    && git -C /djev-spark checkout --quiet "${VLLM_BUILD_REF}" \
    && git clone --quiet "${DJEV_REPO}" /djev \
    && git -C /djev checkout --quiet "${DJEV_REF}"

FROM vllm/vllm-openai:${VLLM_BASE_RELEASE}
ARG VLLM_BASE_RELEASE

# The release ships CUDA libraries without some headers and unversioned .so links.
# The FlashInfer JIT needs both. The script says which.
COPY --from=sources /djev-spark/patches/link_cuda_headers.sh /tmp/link_cuda_headers.sh
RUN bash /tmp/link_cuda_headers.sh && rm /tmp/link_cuda_headers.sh

COPY diffusion-gemma-stack.patch parser-arguments.patch /tmp/hoover4-patches/
RUN version="$(python3 -c 'import vllm; print(vllm.__version__)')" \
    && { [ "v$version" = "${VLLM_BASE_RELEASE}" ] \
         || { echo "the base reports vLLM $version, and the patches need ${VLLM_BASE_RELEASE}" >&2; exit 1; }; } \
    && site="$(python3 -c 'import os, vllm; print(os.path.dirname(os.path.dirname(vllm.__file__)))')" \
    && for p in diffusion-gemma-stack parser-arguments; do \
         patch --forward --batch --no-backup-if-mismatch -p1 -d "$site" < /tmp/hoover4-patches/$p.patch || exit 1; \
       done \
    && find "$site"/vllm -name '__pycache__' -prune -exec rm -rf {} + \
    && python3 -m compileall -q "$site"/vllm/model_executor/models/diffusion_gemma.py \
         "$site"/vllm/v1/core/sched/diffusion_scheduler.py "$site"/vllm/config/diffusion.py \
         "$site"/vllm/utils/diffusion.py "$site"/vllm/parser/engine/parser_engine.py \
    && grep -q "hoover4 patch" "$site"/vllm/parser/engine/parser_engine.py \
    && rm -rf /tmp/hoover4-patches

# The worker memory cap. TORCH_MEM_FRACTION arms it at run time.
COPY --from=sources /djev-spark/patches/spark_mem_trace.py /usr/local/lib/python3.12/dist-packages/spark_mem_trace.py
COPY --from=sources /djev-spark/patches/worker_memory_cap.py /tmp/worker_memory_cap.py
RUN python3 /tmp/worker_memory_cap.py && rm /tmp/worker_memory_cap.py

COPY --from=sources /djev/structured_server.py /opt/dgemma/structured_server.py
COPY --from=sources /djev-spark/pages/ /opt/dgemma/pages/
COPY --from=sources /djev-spark/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && python3 -m py_compile /opt/dgemma/structured_server.py

# The image check of djev-spark, without its FlashInfer per-request causal check. hoover4
# runs the Triton attention backend, so the image does not carry that change.
COPY --from=sources /djev-spark/patches/verify_image.py /tmp/verify_image.py
RUN [ "$(grep -c '_plan_split_prefill' /tmp/verify_image.py)" = 1 ] \
    && sed -i '/_plan_split_prefill/d' /tmp/verify_image.py \
    && python3 /tmp/verify_image.py && rm /tmp/verify_image.py

# 8000 vLLM (OpenAI API), 8011 structured decisions
EXPOSE 8000 8011
ENTRYPOINT ["/entrypoint.sh"]
