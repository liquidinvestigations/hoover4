# check=skip=InvalidDefaultArgInFrom
# The image of hoover4-vllm: eugr/spark-vllm-b12x pinned by digest, with PLE_QUEUE_DEPTH added.
# BASE_IMAGE has no default. deploy.py pins it in QWEN_FLASH_BASE_IMAGE, and
# ai_services/compose/vllm.yaml passes it in. A change of BASE_IMAGE changes the image tag
# QWEN_FLASH_IMAGE with it.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# The file the patch is written against, and its sha256 in the pinned base. The build stops if they differ.
ARG PLE_DISK_PY=/usr/local/lib/python3.12/dist-packages/flashinfer/experimental/b12x/sequence/ple_embedding/_disk.py
ARG PLE_DISK_SHA256=2232d15d5034d9c0cfb9dc3bdbf0e3f49bcc619f51c9ccee77364a0553c6ddeb

COPY ple_queue_depth.py /tmp/ple_queue_depth.py
RUN python3 /tmp/ple_queue_depth.py "${PLE_DISK_PY}" "${PLE_DISK_SHA256}" \
 && rm /tmp/ple_queue_depth.py

ARG BASE_IMAGE
LABEL io.github.qwen38-flash-next-fp4.base="${BASE_IMAGE}" \
      io.github.qwen38-flash-next-fp4.ple-queue-depth="env PLE_QUEUE_DEPTH, default 256"
