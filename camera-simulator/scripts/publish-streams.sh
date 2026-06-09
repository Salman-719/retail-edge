#!/bin/sh
set -eu

STREAMS_FILE="${STREAMS_FILE:-/config/streams.csv}"
RTSP_SERVER="${RTSP_SERVER:-rtsp-server}"
RTSP_PORT="${RTSP_PORT:-8554}"
PUBLISH_MODE="${PUBLISH_MODE:-copy}"
OUTPUT_FPS="${OUTPUT_FPS:-15}"
OUTPUT_WIDTH="${OUTPUT_WIDTH:-1280}"
FFMPEG_LOGLEVEL="${FFMPEG_LOGLEVEL:-warning}"
RESTART_DELAY_SECONDS="${RESTART_DELAY_SECONDS:-2}"
SYNC_START_DELAY_SECONDS="${SYNC_START_DELAY_SECONDS:-3}"

if [ ! -f "$STREAMS_FILE" ]; then
  echo "streams file not found: $STREAMS_FILE" >&2
  exit 1
fi

mkdir -p /logs

trim() {
  printf '%s' "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

pids=""

cleanup() {
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}

trap cleanup INT TERM EXIT

start_stream() {
  name="$1"
  source="$2"
  path="$3"
  start_epoch="$4"
  url="rtsp://${RTSP_SERVER}:${RTSP_PORT}/${path}"
  log="/logs/${name}.log"
  is_image="false"

  case "$source" in
    *.jpg|*.jpeg|*.JPG|*.JPEG|*.png|*.PNG) is_image="true" ;;
  esac

  (
    while [ "$(date +%s)" -lt "$start_epoch" ]; do
      sleep 0.05
    done

    echo "starting ${name} at epoch ${start_epoch}: ${source} -> ${url}"

    if [ "$is_image" = "true" ]; then
      vf="scale=${OUTPUT_WIDTH}:-2,format=yuv420p"
      ffmpeg -hide_banner -loglevel "$FFMPEG_LOGLEVEL" \
        -re -loop 1 -framerate "$OUTPUT_FPS" -i "$source" \
        -map 0:v:0 -vf "$vf" \
        -c:v libx264 -preset veryfast -tune stillimage \
        -g "$OUTPUT_FPS" -an \
        -rtsp_transport tcp -f rtsp "$url"
    elif [ "$PUBLISH_MODE" = "h264" ]; then
      vf="fps=${OUTPUT_FPS},scale=${OUTPUT_WIDTH}:-2"
      ffmpeg -hide_banner -loglevel "$FFMPEG_LOGLEVEL" \
        -re -stream_loop -1 -i "$source" \
        -map 0:v:0 -vf "$vf" \
        -c:v libx264 -preset veryfast -tune zerolatency \
        -pix_fmt yuv420p -an \
        -rtsp_transport tcp -f rtsp "$url"
    else
      ffmpeg -hide_banner -loglevel "$FFMPEG_LOGLEVEL" \
        -re -stream_loop -1 -i "$source" \
        -map 0:v:0 -an \
        -c:v copy \
        -rtsp_transport tcp -f rtsp "$url"
    fi
  ) >"$log" 2>&1 &

  pids="$pids $!"
}

while true; do
  pids=""
  count=0
  start_epoch="$(($(date +%s) + SYNC_START_DELAY_SECONDS))"

  while IFS=, read -r raw_name raw_source raw_path _rest || [ -n "${raw_name:-}" ]; do
    name="$(trim "${raw_name:-}")"
    source="$(trim "${raw_source:-}")"
    path="$(trim "${raw_path:-}")"

    case "$name" in
      ""|\#*) continue ;;
    esac

    if [ -z "$source" ]; then
      echo "skipping ${name}: missing source path" >&2
      continue
    fi

    if [ -z "$path" ]; then
      path="$name"
    fi

    if [ ! -f "$source" ]; then
      echo "source file does not exist for ${name}: ${source}" >&2
      cleanup
      exit 1
    fi

    start_stream "$name" "$source" "$path" "$start_epoch"
    count=$((count + 1))
  done < "$STREAMS_FILE"

  if [ "$count" -eq 0 ]; then
    echo "no streams configured in $STREAMS_FILE" >&2
    exit 1
  fi

  echo "armed ${count} RTSP publisher(s) for synchronized epoch ${start_epoch}"

  group_running=true
  while "$group_running"; do
    for pid in $pids; do
      if ! kill -0 "$pid" 2>/dev/null; then
        group_running=false
        break
      fi
    done
    "$group_running" && sleep 1
  done

  echo "a publisher exited; restarting the complete synchronized group in ${RESTART_DELAY_SECONDS}s"
  cleanup
  pids=""
  sleep "$RESTART_DELAY_SECONDS"
done
