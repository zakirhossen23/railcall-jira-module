"use strict";

/**
 * Shared axios client for the Jira REST API v3.
 *
 * Builds a configured client from the environment (see auth/jiraAuth.js),
 * attaches Basic Auth, and normalizes error responses into clear messages
 * for the common failure modes (401 / 400 / 403 / 404 / 429 / timeout).
 */

const axios = require("axios");
const { getJiraConfig, buildBasicAuthToken } = require("../auth/jiraAuth");

/**
 * Create an axios client pre-wired to Jira.
 * @param {object} [options]
 * @param {number} [options.timeout]  request timeout in ms (default 15000)
 * @returns {import("axios").AxiosInstance}
 */
function createJiraClient(options = {}) {
  const { baseUrl } = getJiraConfig();
  const timeout = options.timeout || 15000;

  const client = axios.create({
    baseURL: `${baseUrl}/rest/api/3`,
    timeout,
    headers: {
      Authorization: `Basic ${buildBasicAuthToken()}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
  });

  client.interceptors.response.use(
    (response) => response,
    (error) => {
      throw mapJiraError(error);
    }
  );

  return client;
}

/**
 * Translate an axios error into a human-friendly Error for Jira.
 * @param {Error & {response?: object, code?: string, config?: object}} error
 * @returns {Error}
 */
function mapJiraError(error) {
  if (error.response) {
    const { status, data } = error.response;
    const serverMessage = extractMessage(data);
    switch (status) {
      case 400:
        return new Error(`Jira 400 Bad Request: ${serverMessage || "the request payload was invalid"}`);
      case 401:
        return new Error(
          "Jira 401 Unauthorized: check JIRA_EMAIL and JIRA_API_TOKEN. " +
            "Generate a token at https://id.atlassian.com/manage-profile/security/api-tokens"
        );
      case 403:
        return new Error(`Jira 403 Forbidden: your account lacks permission. ${serverMessage}`.trim());
      case 404:
        return new Error(`Jira 404 Not Found: ${serverMessage || "the issue or project does not exist"}`);
      case 429:
        return new Error("Jira 429 Too Many Requests: rate limit hit — retry after a short backoff");
      default:
        return new Error(`Jira ${status}: ${serverMessage || error.message}`);
    }
  }
  if (error.code === "ECONNABORTED") {
    return new Error(`Jira request timed out after ${(error.config && error.config.timeout) || "?"}ms`);
  }
  if (error.code === "ENOTFOUND") {
    return new Error(`Jira host not found (ENOTFOUND) — check JIRA_DOMAIN`);
  }
  if (error.code === "ECONNREFUSED") {
    return new Error(`Jira connection refused (ECONNREFUSED) — check JIRA_DOMAIN and your network`);
  }
  if (error.code === "ERR_BAD_REQUEST") {
    return new Error(`Jira bad request: ${error.message}`);
  }
  return new Error(`Jira request failed: ${error.message}`);
}

/** Pull the most useful message out of a Jira error body. */
function extractMessage(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (Array.isArray(data.errorMessages) && data.errorMessages.length) {
    return data.errorMessages.join("; ");
  }
  // Field-level errors, e.g. { "errors": { "issuetype": "Specify a valid issue type" } }
  if (data.errors && typeof data.errors === "object") {
    const parts = Object.entries(data.errors)
      .filter(([, v]) => v)
      .map(([k, v]) => `${k}: ${v}`);
    if (parts.length) return parts.join("; ");
  }
  if (data.message) return data.message;
  return "";
}

module.exports = { createJiraClient, mapJiraError };
