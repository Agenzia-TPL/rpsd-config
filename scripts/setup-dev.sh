#!/bin/bash

if [ ! -s uv.lock ]; then
    rm uv.lock
fi
uv sync --dev
