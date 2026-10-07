#!/usr/bin/env bash
# Run the browser server and its private Xvfb display as one service.
set -u

display="${DISPLAY:-:99}"
width="${BROWSER_WINDOW_WIDTH:-1280}"
height="${BROWSER_WINDOW_HEIGHT:-720}"
socket="/tmp/.X11-unix/X${display#:}"
rm -f "$socket" "/tmp/.X${display#:}-lock"
Xvfb "$display" -screen 0 "${width}x${height}x24" -nolisten tcp -nolisten local &
xvfb=$!
for _ in $(seq 100); do
    [ -S "$socket" ] && break
    kill -0 "$xvfb" 2>/dev/null || break
    sleep 0.1
done
if [ ! -S "$socket" ]; then
    echo "The browser display did not start." >&2
    kill -TERM "$xvfb" 2>/dev/null
    exit 1
fi
export DISPLAY="$display"
python -m browser_use_server.server &
server=$!
stop_server() {
    kill -TERM "$server" 2>/dev/null
    for _ in $(seq 200); do
        kill -0 "$server" 2>/dev/null || return 0
        sleep 0.1
    done
    kill -KILL "$server" 2>/dev/null
}
trap 'stop_server' TERM INT
wait -n "$xvfb" "$server"
status=$?
if kill -0 "$server" 2>/dev/null; then
    stop_server
    wait "$server" 2>/dev/null
fi
kill -TERM "$xvfb" 2>/dev/null
wait "$xvfb" 2>/dev/null
exit "$status"
