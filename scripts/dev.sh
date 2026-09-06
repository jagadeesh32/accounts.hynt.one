#!/usr/bin/env bash
#
# Start the whole Hynt estate locally.
#
#   ./scripts/dev.sh              accounts only (backend + SPA)
#   ./scripts/dev.sh all          accounts + all three platforms
#   ./scripts/dev.sh terminal     accounts + one platform
#   ./scripts/dev.sh stop         free every port this script uses
#   ./scripts/dev.sh all --force  stop leftovers first, then start
#
# Everything reaches the identity provider at http://localhost:5170 — the
# accounts Vite server, proxying through to the backend on :9000. That single
# origin is what makes the SSO cookie work in dev: it is host-only on localhost,
# and cookies ignore the port, so one set at :5170 is sent from :5174 too.
set -uo pipefail

HYNT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ACCOUNTS="$HYNT_ROOT/accounts.hynt.one"

# label → "port dir command..."
declare -A WEB_PORT=( [accounts]=5170 [terminal]=5174 [xterminal]=5175 [intelligence]=5176 )
declare -A API_PORT=( [accounts]=9000 [terminal]=8000 [xterminal]=8001 [intelligence]=8100 )

CHILD_PIDS=()

# ── ports ────────────────────────────────────────────────────────────────────
pid_on_port() {
  ss -lntp 2>/dev/null | grep ":$1 " | grep -oP 'pid=\K[0-9]+' | head -1
}

free_port() {
  local port=$1 pid
  pid="$(pid_on_port "$port")"
  [[ -z "$pid" ]] && return 0
  kill "$pid" 2>/dev/null
  for _ in 1 2 3 4 5 6; do
    sleep 0.25
    [[ -z "$(pid_on_port "$port")" ]] && return 0
  done
  # Vite forks workers that survive a polite TERM and keep holding the socket,
  # which makes the *next* run fail with "address already in use" for no visible
  # reason. Escalate rather than leave that landmine.
  kill -9 "$pid" 2>/dev/null
  sleep 0.25
}

stop_all() {
  local freed=0
  for port in "${WEB_PORT[@]}" "${API_PORT[@]}"; do
    if [[ -n "$(pid_on_port "$port")" ]]; then
      free_port "$port"
      freed=$((freed + 1))
    fi
  done
  echo "freed $freed port(s)"
}

cleanup() {
  trap - EXIT INT TERM
  echo
  echo "stopping…"
  for pid in "${CHILD_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  # Kill by port as well as by pid: a child started through `npm run dev` is a
  # shell wrapping node wrapping Vite, and killing the wrapper does not always
  # take the process actually holding the socket.
  for port in "${WEB_PORT[@]}" "${API_PORT[@]}"; do
    free_port "$port"
  done
  wait 2>/dev/null || true
}

# ── args ─────────────────────────────────────────────────────────────────────
TARGET="${1:-accounts}"
FORCE=0
for arg in "$@"; do [[ "$arg" == "--force" ]] && FORCE=1; done

if [[ "$TARGET" == "stop" ]]; then
  stop_all
  exit 0
fi

case "$TARGET" in
  all)                                  PLATFORMS=(terminal xterminal intelligence) ;;
  accounts)                             PLATFORMS=() ;;
  terminal|xterminal|intelligence)      PLATFORMS=("$TARGET") ;;
  *) echo "usage: $0 [accounts|terminal|xterminal|intelligence|all|stop] [--force]" >&2; exit 2 ;;
esac

# ── preflight ────────────────────────────────────────────────────────────────
# Check before starting anything. Half a stack up and half of it erroring is
# much harder to read than one clear message up front.
NEEDED=(accounts "${PLATFORMS[@]:-}")
BUSY=()
for name in "${NEEDED[@]:-}"; do
  [[ -z "$name" ]] && continue
  for port in "${WEB_PORT[$name]}" "${API_PORT[$name]}"; do
    pid="$(pid_on_port "$port")"
    [[ -n "$pid" ]] && BUSY+=("$port (pid $pid, $(ps -p "$pid" -o comm= 2>/dev/null || echo '?'))")
  done
done

if (( ${#BUSY[@]} )); then
  if (( FORCE )); then
    echo "freeing ports already in use…"
    stop_all
    echo
  else
    echo "These ports are already in use:" >&2
    printf '  %s\n' "${BUSY[@]}" >&2
    echo >&2
    echo "Most likely a previous run is still going. Either:" >&2
    echo "  ./scripts/dev.sh stop          # free them" >&2
    echo "  ./scripts/dev.sh $TARGET --force   # free them and start" >&2
    exit 1
  fi
fi

trap cleanup EXIT INT TERM

# ── start ────────────────────────────────────────────────────────────────────
start() {  # start <label> <dir> <command...>
  local label=$1 dir=$2; shift 2
  if [[ ! -d "$dir" ]]; then
    echo "  skip  $label (no $dir)"
    return
  fi
  ( cd "$dir" && exec "$@" ) 2>&1 | sed "s/^/[$label] /" &
  CHILD_PIDS+=($!)
  printf '  up    %s\n' "$label"
}

wait_for() {  # wait_for <url> <label>
  for _ in $(seq 1 60); do
    curl -sf -m 2 "$1" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  echo "  WARN  $2 did not answer at $1" >&2
}

echo "Hynt local stack"
echo

start "accounts-api" "$ACCOUNTS/backend" .venv/bin/python -m app.main
wait_for "http://127.0.0.1:${API_PORT[accounts]}/api/v1/health" "accounts-api"
start "accounts-web" "$ACCOUNTS/frontend" npm run dev -- --host localhost

for name in "${PLATFORMS[@]:-}"; do
  [[ -z "$name" ]] && continue
  dir="$HYNT_ROOT/$name.hynt.one"
  start "$name-api" "$dir/backend" \
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT[$name]}"
  start "$name-web" "$dir/frontend" npm run dev -- --host localhost
done

cat <<BANNER

  ─────────────────────────────────────────────────────────
   Accounts       http://localhost:5170
   Terminal       http://localhost:5174
   X-Terminal     http://localhost:5175
   Intelligence   http://localhost:5176

   Sign in at Accounts, then open a platform — it should not
   ask you again. That is the whole thing working.

   Use localhost, never 127.0.0.1 — to a browser those are
   different hosts and the SSO cookie will not be sent.
  ─────────────────────────────────────────────────────────

  Ctrl-C to stop everything.

BANNER

wait
