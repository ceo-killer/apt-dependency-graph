#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m apt_graph "$@"
