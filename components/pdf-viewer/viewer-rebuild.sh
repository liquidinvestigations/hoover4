#!/bin/bash
set -ex
(
    cd embed-pdf-viewer
    # time pnpm install
    time pnpm build
)
mkdir -p _viewer/dist
rm -rf _viewer/dist/*
cp -a embed-pdf-viewer/viewers/snippet/dist/ _viewer/