"use strict";

/**
 * Creates a Jira issue.
 *
 * POST /rest/api/3/issue
 * Body: { "fields": { "project": {"key"}, "summary", "description", "issuetype" } }
 *
 * @param {object} params
 * @param {string} params.projectKey   - the project key, e.g. "PROJ"
 * @param {string} params.summary      - the issue title/summary
 * @param {string|object} [params.description] - plain text, or an ADF doc
 * @param {string} [params.issueType="Task"]   - issue type name (or id)
 * @param {object} [params.extraFields]        - any additional fields to set
 * @returns {Promise<{id: string, key: string, self: string}>}
 */

const { createJiraClient } = require("../lib/jiraClient");
const { toAdfDescription } = require("../lib/adf");

async function createIssue({ projectKey, summary, description, issueType = "Task", extraFields = {} }) {
  if (!projectKey) throw new Error("createIssue: projectKey is required");
  if (!summary) throw new Error("createIssue: summary is required");

  const fields = {
    project: { key: projectKey },
    summary,
    issuetype: { name: issueType },
    ...extraFields,
  };

  if (description !== undefined && description !== null && description !== "") {
    fields.description = toAdfDescription(description);
  }

  const client = createJiraClient();
  const { data } = await client.post("/issue", { fields });

  return { id: data.id, key: data.key, self: data.self };
}

module.exports = { createIssue };
