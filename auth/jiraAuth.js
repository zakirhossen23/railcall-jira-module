"use strict";

/**
 * Jira authentication helpers.
 *
 * Reads Jira Cloud credentials from the environment and produces the Basic
 * Auth token used for every REST API v3 call.
 *
 * Required environment variables:
 *   JIRA_DOMAIN     e.g. "yourcompany.atlassian.net"  (scheme optional)
 *   JIRA_EMAIL      the account email tied to the API token
 *   JIRA_API_TOKEN  token from https://id.atlassian.com/manage-profile/security/api-tokens
 */

function getJiraConfig() {
  const domain = (process.env.JIRA_DOMAIN || "").trim();
  const email = (process.env.JIRA_EMAIL || "").trim();
  const apiToken = (process.env.JIRA_API_TOKEN || "").trim();

  const missing = [];
  if (!domain) missing.push("JIRA_DOMAIN");
  if (!email) missing.push("JIRA_EMAIL");
  if (!apiToken) missing.push("JIRA_API_TOKEN");

  if (missing.length > 0) {
    throw new Error(
      `Missing Jira environment variable(s): ${missing.join(", ")}. ` +
        "Set them in your environment or a .env file (see .env.example)."
    );
  }

  // Normalize the domain. An explicit scheme is respected (http:// lets you
  // point at a local mock during development); otherwise default to https.
  // Trailing slashes are stripped.
  let baseUrl = domain.replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `https://${baseUrl}`;
  }
  const host = baseUrl.replace(/^https?:\/\//i, "").replace(/\/+$/, "");

  return { domain: host, email, apiToken, baseUrl };
}

/**
 * Returns the Base64 Basic Auth token ("<email>:<apiToken>").
 * @returns {string} base64-encoded token
 */
function buildBasicAuthToken() {
  const { email, apiToken } = getJiraConfig();
  return Buffer.from(`${email}:${apiToken}`, "utf8").toString("base64");
}

/**
 * Returns the full `Authorization` header value, e.g. "Basic dXNlcjp0b2tlbg==".
 * @returns {string}
 */
function buildAuthorizationHeader() {
  return `Basic ${buildBasicAuthToken()}`;
}

module.exports = { getJiraConfig, buildBasicAuthToken, buildAuthorizationHeader };
