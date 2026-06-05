# ha-bambuddy

A standalone HA addon for BambuBuddy — forked from
[Spegeli/homeassistant-app-bambuddy](https://github.com/Spegeli/homeassistant-app-bambuddy)
with no upstream tracking. The goal is to own the addon wrapper while continuing
to pull the BambuBuddy app from its upstream image
([maziggy/bambuddy](https://github.com/maziggy/bambuddy)).

## Why this fork exists

BambuBuddy's Virtual Printer feature does not work on HAOS. The VP services fail
to start. The root cause has not been fully confirmed yet — this repo exists to
investigate and fix it properly.

Do NOT arrive at conclusions before investigating. Read the Dockerfile and addon
structure first to understand what's happening before proposing changes.

## Environment

- HA install: Home Assistant OS running as a Hyper-V VM
- HA VM IP: `192.168.250.20` (eth1 / management), `10.1.1.12` (eth0 / LAN)
- This Ubuntu VM hosts Claude Code; edits flow via git commit/push → user pulls on HA VM
- SSHFS mounts: `/mnt/ha/config/` → HA VM `/homeassistant/`, `/mnt/ha/addon_configs/` → HA VM `/addon_configs/`
- SSH alias `ha` → `root@192.168.250.20:22222` using `~/.ssh/ha_ed25519`

## Currently installed addon

- Source repo forked from: `https://github.com/Spegeli/homeassistant-app-bambuddy`
- Installed slug: `bd367cad_bambuddy_daily`
- Addon data lives at: `/mnt/ha/addon_configs/bd367cad_bambuddy_daily/`
- SQLite DB: `/mnt/ha/addon_configs/bd367cad_bambuddy_daily/data/bambuddy.db`

## Virtual Printer — current state

The VP "VP Sharkie" (`id=1`) is configured in queue mode targeting the physical P2S.

- `bind_ip` was written directly to the SQLite DB as `192.168.250.220` — this was
  a workaround attempt during troubleshooting, not a confirmed fix
- VP is `enabled=0` — intentionally left disabled
- A secondary IP `192.168.250.220/24` was added to eth1 on the HA host persistently
  via `ha network update` and is confirmed present

## Known symptom

BambuBuddy logs show warnings from `backend.app.services.network_utils` at startup.
The VP bind interface dropdown in the UI does not show the alias IP `192.168.250.220`.
VP services do not start when the VP is enabled.

Investigate the addon and app code to understand why before touching anything.

## Workflow rules (same as main HA config project)

- Edits flow: Claude Code (here) → commit & push → user pulls on HA VM
- Claude never SSH-pulls on the HA VM — user owns the pull step
- Never modify `.storage/`
- Validate before committing
