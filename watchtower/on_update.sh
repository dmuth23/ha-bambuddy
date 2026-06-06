#!/bin/bash
# Triggered when Watchtower updates the bambuddy-sentinel container.
# Gets the latest daily version from GitHub, bumps config.yaml if changed,
# then commits + pushes to GitHub.
#
# HA is NOT touched from here — the HA admin dashboard "Reload Addon Store"
# button + BambuBuddy Update tile are the user-controlled install path.
# This VM is not in the critical path for HA operation.

set -euo pipefail

ADDON_REPO="/home/dmadmin/projects/ha-bambuddy"
CONFIG="$ADDON_REPO/bambuddy-daily/config.yaml"
LOG_FILE="$ADDON_REPO/watchtower/update.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"; }

log "on_update triggered — checking for new version"

# Get latest daily release tag from GitHub (public API, no auth needed)
LATEST=$(curl -s "https://api.github.com/repos/maziggy/bambuddy/releases" \
  | python3 -c "
import sys, json
releases = json.load(sys.stdin)
daily = [r for r in releases if 'daily' in r.get('tag_name', '')]
print(daily[0]['tag_name'].lstrip('v') if daily else '', end='')
")

if [ -z "$LATEST" ]; then
  log "ERROR: could not determine latest version from GitHub API"
  exit 1
fi

log "Latest upstream: $LATEST"

# Get current version from config.yaml
CURRENT=$(grep '^version:' "$CONFIG" | sed 's/version: *"\(.*\)"/\1/')
log "Current config:  $CURRENT"

if [ "$CURRENT" = "$LATEST" ]; then
  log "Already up to date — nothing to do"
  exit 0
fi

log "Bumping $CURRENT → $LATEST"

sed -i "s/version: \"$CURRENT\"/version: \"$LATEST\"/" "$CONFIG"

cd "$ADDON_REPO"
git -c user.name="bambuddy-bot" -c user.email="bot@localhost" \
  add bambuddy-daily/config.yaml
git -c user.name="bambuddy-bot" -c user.email="bot@localhost" \
  commit -m "chore: auto-bump bambuddy-daily to $LATEST"
git push origin main

log "Pushed to GitHub. Use 'Reload Addon Store' on the HA admin dashboard to pick up the update."
