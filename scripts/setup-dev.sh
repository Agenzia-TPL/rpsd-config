#!/usr/bin/env bash
set -euo pipefail

if [ ! -s uv.lock ]; then
    rm uv.lock
fi
uv sync --dev
