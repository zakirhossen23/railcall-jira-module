#!/usr/bin/env node
"use strict";

/**
 * validate-jira.js — verify the module can talk to your real Jira instance.
 *
 * Loads .env, then:
 *   1. checks the required env vars are present
 *   2. calls GET /rest/api/3/myself  (proves the credentials work)
 *   3. runs a small JQL search to prove read access
 *
 * Usage:
 *   node scripts/validate-jira.js
 */

const { loadEnv } = require("../lib/loadEnv");
const { getJiraConfig } = require("../auth/jiraAuth");
const { createJiraClient } = require("../lib/jiraClient");

async function main() {
  loadEnv();

  let cfg;
  try {
    cfg = getJiraConfig();
  } catch (err) {
    console.error(`✗ ${err.message}`);
    console.error("  → Fill in .env (see .env.example) and try again.");
    process.exit(1);
  }

  console.log(`Jira instance : ${cfg.baseUrl}`);
  console.log(`Account email : ${cfg.email}`);
  console.log("");

  const client = createJiraClient();

  // 1) Credentials check
  try {
    const { data } = await client.get("/myself");
    console.log(`✓ Credentials OK — logged in as "${data.displayName}" <${data.emailAddress}>`);
  } catch (err) {
    console.error(`✗ Credentials rejected: ${err.message}`);
    console.error("  → Generate a fresh API token at https://id.atlassian.com/manage-profile/security/api-tokens");
    console.error("    and paste it into .env as JIRA_API_TOKEN=...");
    process.exit(1);
  }

  // 2) Read access check (small bounded JQL search — new /search/jql endpoint)
  try {
    const { data } = await client.post("/search/jql", {
      jql: "created >= -30d ORDER BY created DESC",
      maxResults: 5,
      fields: ["summary", "status"],
    });
    const issues = data.issues || [];
    console.log(`✓ Search OK — ${issues.length} issue(s) returned${data.isLast ? "" : " (more pages available)"}:`);
    for (const issue of issues) {
      const status = issue.fields && issue.fields.status ? issue.fields.status.name : "?";
      console.log(`    ${issue.key}  [${status}]  ${(issue.fields && issue.fields.summary) || "(no summary)"}`);
    }
  } catch (err) {
    console.error(`✗ Search failed: ${err.message}`);
    process.exit(1);
  }

  console.log("");
  console.log("✅ All checks passed — the module is ready to use against your Jira.");
}

main().catch((err) => {
  console.error("Unexpected error:", err);
  process.exit(1);
});