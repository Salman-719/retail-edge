#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

docker compose ps
echo
echo "Publisher logs:"
docker compose logs --tail=80 publisher
