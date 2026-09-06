#!/usr/bin/env bash
# Backend on :9000, frontend on :5170. Ctrl-C stops both.
#
# The cookie is forced host-only and insecure: on localhost there is no parent
# domain to share it across, and a Secure cookie is dropped on plain HTTP.
set -euo pipefail
cd "$(dirname "$0")/.."

export HYNT_COOKIE_DOMAIN=""
export HYNT_COOKIE_SECURE=false
export HYNT_ISSUER="http://localhost:5170"

trap 'kill 0' EXIT
(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload) &
(cd frontend && npm run dev) &
wait
