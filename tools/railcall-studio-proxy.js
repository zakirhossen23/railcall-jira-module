#!/usr/bin/env node
/**
 * railcall-studio-proxy.js
 *
 * Lets RailCall Studio work through GitHub Codespaces / forwarded ports
 * WITHOUT modifying the installed RailCall code.
 *
 * Why this exists
 * --------------
 * RailCall Studio binds to 127.0.0.1:8799 and enforces a DNS-rebinding guard
 * that only accepts loopback Host/Origin/Referer. In a Codespace the browser
 * reaches forwarded ports via https://<codespace>-<port>.app.github.dev, so
 * those headers are the Codespace domain and the guard rejects every request
 * with "cross-origin blocked (loopback only)".
 *
 * This proxy listens on 0.0.0.0:<port> (reachable through the forwarded port),
 * rewrites Host/Origin/Referer back to loopback, and forwards to the Studio.
 * From the Studio's point of view every request looks like it came from
 * 127.0.0.1:8799, so the stock, unmodified guard passes — and the patch
 * survives `railcall update` because RailCall itself is never touched.
 *
 * Usage
 * -----
 *   node tools/railcall-studio-proxy.js
 *
 * Env overrides (defaults shown):
 *   RAILCALL_PROXY_HOST       0.0.0.0
 *   RAILCALL_PROXY_PORT       8899
 *   RAILCALL_UPSTREAM         127.0.0.1
 *   RAILCALL_UPSTREAM_PORT    8799
 */
"use strict";

const http = require("http");

const LISTEN_HOST = process.env.RAILCALL_PROXY_HOST || "0.0.0.0";
const LISTEN_PORT = parseInt(process.env.RAILCALL_PROXY_PORT || "8899", 10);
const UPSTREAM_HOST = process.env.RAILCALL_UPSTREAM || "127.0.0.1";
const UPSTREAM_PORT = parseInt(process.env.RAILCALL_UPSTREAM_PORT || "8799", 10);

const LOOPBACK_ORIGIN = `http://${UPSTREAM_HOST}:${UPSTREAM_PORT}`;

/** Copy a request's headers, rewriting the ones the Studio's guard inspects. */
function forwardHeaders(req) {
  const headers = { ...req.headers };
  // Host must be loopback for the Studio's ALLOWED_HOSTS check.
  headers.host = `${UPSTREAM_HOST}:${UPSTREAM_PORT}`;
  // Origin / Referer must be loopback for the CSRF + cross-origin checks.
  if (headers.origin) headers.origin = LOOPBACK_ORIGIN;
  if (headers.referer) headers.referer = `${LOOPBACK_ORIGIN}${req.url}`;
  return headers;
}

const server = http.createServer((req, res) => {
  const upstreamReq = http.request(
    {
      host: UPSTREAM_HOST,
      port: UPSTREAM_PORT,
      method: req.method,
      path: req.url,
      headers: forwardHeaders(req),
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode, upstreamRes.headers);
      upstreamRes.pipe(res);
    }
  );

  upstreamReq.on("error", (err) => {
    res.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
    res.end(`RailCall proxy: bad gateway -> ${UPSTREAM_HOST}:${UPSTREAM_PORT} (${err.message})\n`);
  });

  req.pipe(upstreamReq);
});

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  console.log(
    `RailCall Studio proxy ready:\n` +
      `  browser  -> http://${LISTEN_HOST}:${LISTEN_PORT}   (forward this port in Codespaces)\n` +
      `  upstream -> http://${UPSTREAM_HOST}:${UPSTREAM_PORT}   (RailCall Studio)`
  );
});

process.on("SIGINT", () => {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 2000).unref();
});
