#!/bin/bash

if [ ! -s uv.lock ]; then
    rm uv.lock
fi
uv sync --dev


#!/usr/bin/env bash
set -euo pipefail

apt-get update
apt-get install -y gdal-bin libgdal-dev libproj-dev postgresql-client postgis

