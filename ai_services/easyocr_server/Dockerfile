# GPU EasyOCR over HTTP.
#
# There is no CUDA base image here on purpose. The torch wheels from the CUDA 13 index
# carry their own runtime libraries (libcudart, cuBLAS, cuDNN) as nvidia-*-cu13
# packages, and the only thing that has to come from outside is libcuda.so.1, which
# nvidia-container-toolkit injects from the host driver at start. A CUDA base image on
# top of that contributes a second, unused copy of the toolkit and pins the image to one
# CUDA minor for no benefit. Without it, the same Dockerfile builds on x86_64 and aarch64
# and follows whatever driver the host has.
FROM python:3.13-slim AS builder
# Build and thread parallelism, bounded. Left unbounded, every build backend here sizes
# itself to the host's core count at once (pip resolves and compiles several packages in
# parallel, each of which then forks one compiler job per core), and the machine running
# the build stops being usable. One knob feeds every backend that has its own spelling
# for it, because missing one is enough to lose the bound.
ARG BUILD_JOBS=6
ENV BUILD_JOBS=${BUILD_JOBS} \
    MAX_JOBS=${BUILD_JOBS} \
    MAKEFLAGS=-j${BUILD_JOBS} \
    CMAKE_BUILD_PARALLEL_LEVEL=${BUILD_JOBS} \
    NINJAFLAGS=-j${BUILD_JOBS} \
    NPY_NUM_BUILD_JOBS=${BUILD_JOBS} \
    CARGO_BUILD_JOBS=${BUILD_JOBS} \
    RAYON_NUM_THREADS=${BUILD_JOBS} \
    OMP_NUM_THREADS=${BUILD_JOBS} \
    OPENBLAS_NUM_THREADS=${BUILD_JOBS} \
    MKL_NUM_THREADS=${BUILD_JOBS} \
    NUMEXPR_NUM_THREADS=${BUILD_JOBS}

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    VENV_PATH="/opt/venv"

ENV PATH="$VENV_PATH/bin:$PATH"

# Compilers are here for the few dependencies that still have no wheel on one arch or
# the other (pyclipper is the usual one on aarch64). They stay in this stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv $VENV_PATH

COPY requirements.txt /tmp/requirements.txt
RUN $VENV_PATH/bin/pip install --no-cache-dir --upgrade pip \
    && $VENV_PATH/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# Model weights are fetched at build time, like the Tesseract twin's traineddata: a
# service that has to reach the internet before it can answer its first request is one
# that fails in a way the health check cannot report. The compose overlay bind-mounts a
# host folder over this path, and that mount hides what the image has there. The runtime
# stage therefore keeps a second copy at EASYOCR_BAKED_DIR, and the server copies it into
# the cache folder at start. Anything not listed here still works and is downloaded on
# first use.
ARG EASYOCR_LANGUAGES="en"
ENV EASYOCR_MODEL_DIR=/root/.EasyOCR
RUN $VENV_PATH/bin/python - <<'PY'
import os
import easyocr

languages = [c.strip() for c in os.environ["EASYOCR_LANGUAGES"].split("+") if c.strip()]
easyocr.Reader(languages, gpu=False, model_storage_directory=os.environ["EASYOCR_MODEL_DIR"],
               user_network_directory=os.environ["EASYOCR_MODEL_DIR"],
               download_enabled=True, verbose=False)
PY

# ------------------------------------------------------------------ runtime
FROM python:3.13-slim AS runtime
# Thread caps, carried into the runtime image. These services are GPU-bound; the CPU-side
# thread pools (OpenMP inside torch, the tokenizers' rayon pool) otherwise each spin up one
# thread per core and contend with everything else on the box for no throughput gain.
ARG BUILD_JOBS=6
ENV OMP_NUM_THREADS=${BUILD_JOBS} \
    OPENBLAS_NUM_THREADS=${BUILD_JOBS} \
    MKL_NUM_THREADS=${BUILD_JOBS} \
    NUMEXPR_NUM_THREADS=${BUILD_JOBS} \
    RAYON_NUM_THREADS=${BUILD_JOBS}

ENV PYTHONUNBUFFERED=1 \
    VENV_PATH="/opt/venv" \
    EASYOCR_MODEL_DIR=/root/.EasyOCR \
    HOST=0.0.0.0 \
    PORT=8000

ENV PATH="$VENV_PATH/bin:$PATH"

# libgomp is OpenMP for torch and scikit-image; libglib2.0-0 is what opencv-headless
# still links against. Without them the image builds and then fails at `import cv2`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder $VENV_PATH $VENV_PATH
# The first copy serves a run with no mount. The second copy is outside the mount path,
# and the server copies each of its files into EASYOCR_MODEL_DIR at start when the file
# is absent there, so an empty cache folder gets the baked weights before any request.
COPY --from=builder /root/.EasyOCR /root/.EasyOCR
COPY --from=builder /root/.EasyOCR /opt/easyocr-baked
ENV EASYOCR_BAKED_DIR=/opt/easyocr-baked

WORKDIR /app
COPY easyocr_server.py /app/easyocr_server.py

EXPOSE 8000

# One uvicorn worker: concurrency is bounded inside the app, and a second uvicorn
# process would double it behind the app's back, onto one GPU, which is where the
# concurrent-readtext deadlock the app guards against lives.
CMD ["sh", "-c", "uvicorn easyocr_server:app --host ${HOST} --port ${PORT} --workers 1"]
