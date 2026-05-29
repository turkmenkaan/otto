#!/usr/bin/env bash
# Recreate the Otto container. Run from the repo root (so --env-file finds .env).
set -euo pipefail

docker rm -f otto 2>/dev/null || true
docker run -d --name otto \
  --env-file .env \
  --restart unless-stopped \
  --dns 1.1.1.1 --dns 8.8.8.8 \
  -v otto-data:/app/data \
  otto
