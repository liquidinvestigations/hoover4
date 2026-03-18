#!/bin/bash

mkdir -p _server/dist
rm -rf _server/dist/*

cp -a embed-pdf-viewer/packages/pdfium _server/dist/pdfium
cp -a embed-pdf-viewer/packages/engines _server/dist/engines
cp -a embed-pdf-viewer/packages/models _server/dist/models
cp -a embed-pdf-viewer/packages/fonts _server/dist/fonts