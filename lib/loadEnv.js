"use strict";

/**
 * Tiny dependency-free .env loader.
 *
 * Reads KEY=VALUE lines from a .env file into process.env (without
 * overwriting variables that are already set in the real environment).
 * Supports:
 *   - blank lines and # comments
 *   - optional surrounding quotes on values
 *   - inline # comments (only when the value is unquoted)
 *
 * @param {string} [path] - path to the .env file (default: ./.env)
 * @returns {object} the parsed variables
 */
const fs = require("fs");
const path = require("path");

function loadEnv(filePath) {
  const resolved = path.resolve(filePath || ".env");
  const parsed = {};

  if (!fs.existsSync(resolved)) return parsed;

  const lines = fs.readFileSync(resolved, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    const eq = line.indexOf("=");
    if (eq === -1) continue;

    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();

    // Strip inline comment only for unquoted values.
    if (!/^["']/.test(value)) {
      const hash = value.indexOf(" #");
      if (hash !== -1) value = value.slice(0, hash).trim();
    }

    // Strip surrounding quotes.
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    parsed[key] = value;
    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }

  return parsed;
}

module.exports = { loadEnv };