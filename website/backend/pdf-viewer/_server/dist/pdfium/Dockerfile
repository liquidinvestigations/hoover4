# syntax=docker/dockerfile-upstream:master-labs
FROM emscripten/emsdk:3.1.70 AS emsdk-base

ARG  DEBIAN_FRONTEND=noninteractive
ARG  EXTRA_CFLAGS
ARG  EXTRA_LDFLAGS

ENV  INSTALL_DIR=/opt
ENV  CFLAGS="-I$INSTALL_DIR/include $CFLAGS $EXTRA_CFLAGS"
ENV  CXXFLAGS="$CFLAGS"
ENV  LDFLAGS="-L$INSTALL_DIR/lib $LDFLAGS $CFLAGS $EXTRA_LDFLAGS"
ENV  EM_PKG_CONFIG_PATH=$INSTALL_DIR/lib/pkgconfig:/emsdk/upstream/emscripten/system/lib/pkgconfig
ENV  EM_TOOLCHAIN_FILE=$EMSDK/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake
ENV  PKG_CONFIG_PATH=$PKG_CONFIG_PATH:$EM_PKG_CONFIG_PATH
ENV  PATH="/emsdk/upstream/bin:${PATH}"

# --------------------------------------------------------------------------- #
# 1.  Base packages + entr 5.6
# --------------------------------------------------------------------------- #
RUN  apt-get update && \
     apt-get install -y --no-install-recommends \
         pkg-config autoconf automake libtool ragel git yasm \
         subversion lsb-release tzdata keyboard-configuration tini && \
     apt-get clean && rm -rf /var/lib/apt/lists/*

# locale & timezone
RUN  echo "America/Sao_Paulo" >/etc/timezone && \
     dpkg-reconfigure -f noninteractive tzdata && \
     printf 'LANG="en_US.UTF-8"\n' >/etc/default/local

# --------------------------------------------------------------------------- #
# 2.  Node.js – needed by the generator scripts.
# --------------------------------------------------------------------------- #
FROM emsdk-base AS node-setup
RUN  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && \
     sudo apt-get install -y nodejs && \
     sudo apt-get clean && rm -rf /var/lib/apt/lists/*

# ──────────────────────────────────────────────────────────────────────────────
# 3.  depot_tools – GN / Ninja / gclient live here.
# ──────────────────────────────────────────────────────────────────────────────
FROM node-setup AS depot-tools
RUN  git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git \
         -b main /opt/depot-tools
ENV  PATH=${PATH}:/opt/depot-tools

FROM depot-tools AS pdfium-bootstrap
# ------------------------------------------------------------------  CIPD cache
# Work in a throw-away dir so our fork isn’t required yet
WORKDIR /opt/pdfium-bootstrap

# Ask for *just* the minimal deps
RUN gclient config --unmanaged https://pdfium.googlesource.com/pdfium.git
RUN gclient sync --no-history --shallow

# ──────────────────────────────────────────────────────────────────────────────
# 5.  Install PDFium build dependencies.
# ──────────────────────────────────────────────────────────────────────────────
FROM pdfium-bootstrap AS pdfium-deps
RUN  bash -x ./pdfium/build/install-build-deps.sh --no-prompt

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential pkg-config rsync && \
    \
    curl -sSf https://sh.rustup.rs | bash -s -- -y && \
    . "$HOME/.cargo/env" && \
    cargo install --locked watchexec-cli && \
    strip "$HOME/.cargo/bin/watchexec" && \
    rm -rf "$HOME/.cargo/registry" "$HOME/.cargo/git" && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
ENV PATH="$HOME/.cargo/bin:${PATH}"

ENTRYPOINT ["/usr/bin/tini","--"]