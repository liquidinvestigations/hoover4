FROM rust:1.91.0-trixie

RUN curl -L --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/cargo-bins/cargo-binstall/main/install-from-binstall-release.sh | bash

RUN cargo binstall dioxus-cli@0.7.1
RUN apt update -yq && apt install -yq libwebkit2gtk-4.1-dev \
  build-essential \
  curl \
  wget \
  file \
  libxdo-dev \
  libssl-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev lld



WORKDIR /app
ADD frontend frontend
ADD common common
ADD backend backend
ADD Cargo.toml Cargo.toml
ADD Cargo.lock Cargo.lock
# RUN cd frontend && dx build --renderer web || true