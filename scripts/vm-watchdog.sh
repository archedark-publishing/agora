#!/usr/bin/env bash
#
# Agora VM watchdog — runs every 5 minutes via cron on the prod VM.
#
# Checks:
#   1. Docker Compose services (api, db, redis) are running
#   2. App health endpoint returns 200
#   3. No 5xx responses in recent api logs
#   4. Disk usage under threshold
#   5. Memory / load within sane bounds
#
# Alerts via ntfy on state transitions:
#   OK -> PROBLEM   : high-priority alert
#   PROBLEM -> OK   : recovery notice
#   PROBLEM persists: hourly "still broken" reminder
#
# Configuration (written by the deploy workflow, never committed):
#   $HOME/.config/agora-watchdog.conf
#     NTFY_TOPIC="your-ntfy-topic"
#     DEPLOY_PATH="/path/to/checkout"
#
# State lives in $HOME/.local/share/agora-watchdog/.
# Contains no secrets. Safe to keep in the repo.
#
set -euo pipefail

CONFIG_FILE="${AGORA_WATCHDOG_CONFIG:-$HOME/.config/agora-watchdog.conf}"
STATE_DIR="${AGORA_WATCHDOG_STATE:-$HOME/.local/share/agora-watchdog}"
STATE_FILE="$STATE_DIR/state"
REMINDER_EVERY=12   # re-alert every 12 runs (1h) while a problem persists

DISK_WARN_PCT=85
MEM_WARN_PCT=90

# --- load config -----------------------------------------------------------
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "watchdog: missing config $CONFIG_FILE (deploy workflow writes it)" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$CONFIG_FILE"
: "${NTFY_TOPIC:?NTFY_TOPIC not set in $CONFIG_FILE}"
: "${DEPLOY_PATH:?DEPLOY_PATH not set in $CONFIG_FILE}"

mkdir -p "$STATE_DIR"

# --- helpers ---------------------------------------------------------------
problems=()

add_problem() { problems+=("$1"); }

notify() {
  # notify <priority> <tags> <title> <message>
  local priority="$1" tags="$2" title="$3" message="$4"
  curl -s --max-time 15 -X POST "https://ntfy.sh/${NTFY_TOPIC}" \
    -H "Title: ${title}" \
    -H "Priority: ${priority}" \
    -H "Tags: ${tags}" \
    --data-binary "$message" >/dev/null \
    || echo "watchdog: ntfy post failed" >&2
}

# --- check 1: compose services ---------------------------------------------
if [[ -d "$DEPLOY_PATH" ]]; then
  svc_states="$(docker compose -f "$DEPLOY_PATH/docker-compose.yml" ps --format '{{.Service}}:{{.State}}' 2>/dev/null || true)"
  if [[ -z "$svc_states" ]]; then
    add_problem "compose: 'docker compose ps' returned nothing (docker down?)"
  else
    for want in api db redis; do
      state="$(echo "$svc_states" | awk -F: -v s="$want" '$1==s{print $2}')"
      if [[ "$state" != "running" ]]; then
        add_problem "compose: service '$want' state is '${state:-missing}' (want running)"
      fi
    done
  fi
else
  add_problem "compose: DEPLOY_PATH $DEPLOY_PATH not found"
fi

# --- check 2: app health ----------------------------------------------------
if ! curl -sf --max-time 10 http://localhost:8000/api/v1/health >/dev/null 2>&1; then
  add_problem "health: http://localhost:8000/api/v1/health not returning 200"
fi

# --- check 3: 5xx in recent api logs (best effort) --------------------------
if [[ -d "$DEPLOY_PATH" ]]; then
  log_5xx="$(docker compose -f "$DEPLOY_PATH/docker-compose.yml" logs --since 6m api 2>/dev/null \
    | grep -cE '" 5[0-9]{2} ' || true)"
  if [[ "$log_5xx" -gt 0 ]]; then
    add_problem "5xx: ${log_5xx} server-error responses in api logs (last ~6m)"
  fi
fi

# --- check 4: disk ----------------------------------------------------------
while read -r pct mount; do
  # df -P output: Filesystem 1024-blocks Used Available Capacity Mounted
  usepct="${pct%\%}"
  if [[ "$usepct" =~ ^[0-9]+$ ]] && (( usepct >= DISK_WARN_PCT )); then
    add_problem "disk: ${mount} at ${pct} used (>= ${DISK_WARN_PCT}%)"
  fi
done < <(df -P / /var/lib/docker 2>/dev/null | awk 'NR>1{print $5, $6}' | sort -u)

# --- check 5: memory / load --------------------------------------------------
if command -v free >/dev/null; then
  mem_total="$(free -m | awk '/^Mem:/{print $2}')"
  mem_avail="$(free -m | awk '/^Mem:/{print $7}')"
  if [[ "$mem_total" -gt 0 ]]; then
    mem_used_pct=$(( (mem_total - mem_avail) * 100 / mem_total ))
    if (( mem_used_pct >= MEM_WARN_PCT )); then
      add_problem "memory: ${mem_used_pct}% used (>= ${MEM_WARN_PCT}%)"
    fi
  fi
fi
if [[ -r /proc/loadavg ]]; then
  load5="$(awk '{print $2}' /proc/loadavg)"
  nproc="$(nproc 2>/dev/null || echo 1)"
  # alert if 5-min load exceeds 2x core count (awk for float compare)
  if awk -v l="$load5" -v n="$nproc" 'BEGIN{exit !(l > 2*n)}'; then
    add_problem "load: 5-min avg ${load5} exceeds 2x cores (${nproc})"
  fi
fi

# --- state transitions + notify ---------------------------------------------
prev_problems=""
prev_count=0
if [[ -f "$STATE_FILE" ]]; then
  prev_problems="$(sed -n '1p' "$STATE_FILE")"
  prev_count="$(sed -n '2p' "$STATE_FILE" | grep -E '^[0-9]+$' || echo 0)"
fi
if ((${#problems[@]})); then
  curr_problems="$(printf '%s\n' "${problems[@]}" | sort | tr '\n' ';')"
else
  curr_problems=""
fi

send_alert() {
  local body="Agora prod watchdog (${HOSTNAME:-vm}):"
  local p
  for p in "${problems[@]}"; do
    body+=$'\n- '"$p"
  done
  notify "high" "warning,rotating_light" "Agora prod: problem detected" "$body"
}

if [[ -z "$curr_problems" ]]; then
  # all clear
  if [[ -n "$prev_problems" ]]; then
    notify "default" "white_check_mark" "Agora prod: recovered" \
      "All watchdog checks passing again on ${HOSTNAME:-vm}."
  fi
  printf '\n0\n' > "$STATE_FILE"
else
  if [[ "$curr_problems" != "$prev_problems" ]]; then
    # new or changed problem set -> alert immediately
    send_alert
    printf '%s\n1\n' "$curr_problems" > "$STATE_FILE"
  else
    # same problem persists -> hourly reminder
    count=$((prev_count + 1))
    if (( count >= REMINDER_EVERY )); then
      notify "default" "warning" "Agora prod: still failing" \
        "Problem persisting on ${HOSTNAME:-vm}: ${problems[*]}"
      count=0
    fi
    printf '%s\n%s\n' "$curr_problems" "$count" > "$STATE_FILE"
  fi
fi

# exit non-zero when problems exist so cron logs reflect it
[[ -z "$curr_problems" ]]
