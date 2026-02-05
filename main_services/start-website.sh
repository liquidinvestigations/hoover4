#!/bin/bash
set -ex

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
cd "$SCRIPT_DIR"


cd client
# time dx build --package client3 --bin client3 --platform web
dx serve --package client3 --bin client3 --platform web