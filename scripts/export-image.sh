#!/usr/bin/env bash
# Build the Claims Desk image and save it as one file you can send to someone.
# They run:  docker load -i claims-desk-image.tar.gz
#            docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... claims-desk
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-claims-desk-image.tar.gz}"
# The recipient's machine may differ from yours (Apple Silicon vs Intel/AMD); override with PLATFORM=linux/arm64.
PLATFORM="${PLATFORM:-linux/amd64}"
docker build --platform "$PLATFORM" -t claims-desk:latest apps/insurance_claims
docker save claims-desk:latest | gzip > "$OUT"
echo "Saved $OUT ($(du -h "$OUT" | cut -f1), $PLATFORM)"
