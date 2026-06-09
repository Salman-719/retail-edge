#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created camera-simulator/.env from .env.example"
fi

mkdir -p logs

docker compose up -d

detect_host() {
  if [ -n "${SIMULATOR_HOST:-}" ]; then
    printf '%s\n' "$SIMULATOR_HOST"
    return
  fi

  if command -v ipconfig >/dev/null 2>&1; then
    ipconfig getifaddr en0 2>/dev/null && return
    ipconfig getifaddr en1 2>/dev/null && return
  fi

  if command -v ip >/dev/null 2>&1; then
    ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' && return
  fi

  if command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | awk '{print $1}' && return
  fi

  printf '<simulator-ip>\n'
}

set -a
# shellcheck disable=SC1091
source .env
set +a

HOST="$(detect_host)"
PORT="${RTSP_PORT:-8554}"
STREAMS_PATH="${STREAMS_FILE_HOST:-./streams.csv}"
if [[ "$STREAMS_PATH" != /* ]]; then
  STREAMS_PATH="$ROOT/$STREAMS_PATH"
fi

echo
echo "Camera simulator is starting."
echo
echo "Paste these RTSP URLs into EEP camera stream URLs:"
while IFS=, read -r raw_name _raw_source raw_path _rest || [ -n "${raw_name:-}" ]; do
  name="$(printf '%s' "${raw_name:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  path="$(printf '%s' "${raw_path:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  case "$name" in
    ""|\#*) continue ;;
  esac
  [ -n "$path" ] || path="$name"
  echo "  ${name}: rtsp://${HOST}:${PORT}/${path}"
done < "$STREAMS_PATH"
echo
docker compose ps
