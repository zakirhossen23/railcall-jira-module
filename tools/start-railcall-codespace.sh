#!/usr/bin/env bash
# start-railcall-codespace.sh
#
# One-command launcher for running RailCall Studio in a GitHub Codespace /
# dev container. Starts (or reuses) the Studio + a loopback-rewriting reverse
# proxy so the browser's forwarded-port URL works without modifying RailCall.
#
# After this runs, open the forwarded port 8899 in VS Code (Ports panel →
# "Open in Browser") — URL will be https://<codespace>-8899.app.github.dev
#
# Env overrides:
#   RAILCALL_PROXY_PORT   8899   (the port you forward)
#   RAILCALL_UPSTREAM_PORT 8799  (the Studio's real port)
set -euo pipefail

RAILCALL_BIN="${RAILCALL_BIN:-$HOME/.railcall/bin/railcall}"
PROXY_JS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/railcall-studio-proxy.js"
PROXY_PORT="${RAILCALL_PROXY_PORT:-8899}"
UPSTREAM_PORT="${RAILCALL_UPSTREAM_PORT:-8799}"

echo "==> Ensuring RailCall Studio is running (port ${UPSTREAM_PORT}) ..."
if ss -tln 2>/dev/null | grep -q ":${UPSTREAM_PORT} "; then
  echo "    Studio already listening on ${UPSTREAM_PORT} — reusing it."
else
  (nohup "$RAILCALL_BIN" studio --no-open >/tmp/railcall-studio.log 2>&1 &)
  for _ in $(seq 1 30); do
    ss -tln 2>/dev/null | grep -q ":${UPSTREAM_PORT} " && break
    sleep 1
  done
  ss -tln 2>/dev/null | grep -q ":${UPSTREAM_PORT} " \
    && echo "    Studio is up." \
    || { echo "    ERROR: Studio did not start — see /tmp/railcall-studio.log"; exit 1; }
fi

echo "==> Ensuring the reverse proxy is running (port ${PROXY_PORT}) ..."
if ss -tln 2>/dev/null | grep -q ":${PROXY_PORT} "; then
  echo "    Proxy already listening on ${PROXY_PORT} — reusing it."
else
  (nohup node "$PROXY_JS" >/tmp/railcall-studio-proxy.log 2>&1 &)
  for _ in $(seq 1 15); do
    ss -tln 2>/dev/null | grep -q ":${PROXY_PORT} " && break
    sleep 1
  done
  ss -tln 2>/dev/null | grep -q ":${PROXY_PORT} " \
    && echo "    Proxy is up." \
    || { echo "    ERROR: proxy did not start — see /tmp/railcall-studio-proxy.log"; exit 1; }
fi

echo ""
echo "=================================================================="
echo "  RailCall Studio is ready for your Codespace browser:"
echo ""
echo "  1) Open VS Code's Ports panel (Terminal → Ports)"
echo "  2) Forward port ${PROXY_PORT} (if not already), then click 'Open in Browser'"
echo "     → https://<codespace>-${PROXY_PORT}.app.github.dev"
echo ""
echo "  Logs: /tmp/railcall-studio.log  ·  /tmp/railcall-studio-proxy.log"
echo "  (The proxy rewrites Host/Origin to loopback, so RailCall's stock"
echo "   security guard is satisfied — no RailCall files are modified.)"
echo "=================================================================="
