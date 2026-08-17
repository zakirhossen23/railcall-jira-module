"use strict";

/**
 * railcall-jira-module — main entry point.
 *
 * Exposes the four Jira handlers plus the auth helper so the module can be
 * imported and used by RailCall workflows or standalone Node scripts.
 *
 *   const jira = require("railcall-jira-module");
 *   await jira.createIssue({ projectKey: "PROJ", summary: "Hello", description: "World" });
 */

const { createIssue } = require("./handlers/createIssue");
const { updateIssue } = require("./handlers/updateIssue");
const { searchIssues } = require("./handlers/searchIssues");
const { transitionIssue } = require("./handlers/transitionIssue");

const auth = require("./auth/jiraAuth");
const { toAdfDescription } = require("./lib/adf");
const { mapJiraError } = require("./lib/jiraClient");
const { loadEnv } = require("./lib/loadEnv");

// Convenience: if a .env file exists next to the module, load it so the
// handlers work out of the box (real env vars always take precedence).
loadEnv();

module.exports = {
  createIssue,
  updateIssue,
  searchIssues,
  transitionIssue,
  auth,
  toAdfDescription,
  mapJiraError,
};
