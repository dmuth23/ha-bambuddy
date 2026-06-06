#!/bin/bash
# Listens for Docker start events on bambuddy-sentinel.
# Watchtower restarts the sentinel after pulling a new image, which
# triggers this script to run on_update.sh.
#
# Also replays the last 2 hours of events on startup so a brief downtime
# doesn't cause a missed update.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "$(date '+%Y-%m-%d %H:%M:%S') event_listener started"

docker events \
  --filter "container=bambuddy-sentinel" \
  --filter "event=start" \
  --since "2h" \
  --format "{{.Time}} {{.Action}} {{.Actor.Attributes.name}}" \
| while read -r line; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') Docker event: $line"
    "$SCRIPT_DIR/on_update.sh" || echo "$(date '+%Y-%m-%d %H:%M:%S') on_update.sh failed (exit $?)"
done
