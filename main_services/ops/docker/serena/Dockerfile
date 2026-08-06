# Serena MCP server for this repository: symbolic code navigation/editing for the
# agent working on the checkout (see plans/1-part-1.md, Phase A). Dev tooling only —
# it is never part of the deployed stack and binds to 127.0.0.1 via compose/serena.yaml.
#
# The image carries its own language tooling so the language servers never touch the
# checkout's own venvs/caches/target dirs:
#   * pyright (Serena's default Python LS, run via uvx; needs node at runtime)
#   * rust-analyzer + a Rust toolchain matching website/Dockerfile (rust:1.91.0-trixie)
#
# Serena is pinned to a git commit. An unpinned dev tool that rewrites your code is
# not a dev tool, it is a coin flip. Bump SERENA_GIT_REF deliberately.
FROM python:3.13-slim

ARG SERENA_GIT_REF=bcac0969fb8685783ea6d0f2642468fcc47e6395
ARG RUST_TOOLCHAIN=1.91.0

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        nodejs \
        npm \
        build-essential \
        pkg-config \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Rust toolchain, matching website/Dockerfile (rust:1.91.0-trixie). rust-analyzer is
# installed as a rustup component because Serena resolves it via `rustup which
# rust-analyzer`, which guarantees it matches the toolchain. RUSTUP_HOME stays here at
# runtime; the compose file points CARGO_HOME/CARGO_TARGET_DIR into the serena_state
# volume instead, so rust-analyzer's cargo check never writes into the checkout.
ENV RUSTUP_HOME=/opt/rust/rustup \
    CARGO_HOME=/opt/rust/cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sh -s -- -y --default-toolchain "${RUST_TOOLCHAIN}" --profile minimal \
           --component rust-analyzer --component rust-src
ENV PATH=/opt/rust/cargo/bin:$PATH

ENV SERENA_GIT_REF=${SERENA_GIT_REF}

# Warm the uv cache at build time so container start does not re-clone/re-resolve
# serena (and so a restart works offline). UV_CACHE_DIR is repointed into the state
# volume by the compose file at runtime; this pre-warms the image layer only.
RUN uvx --from "git+https://github.com/oraios/serena@${SERENA_GIT_REF}" serena --version

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
