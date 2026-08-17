"use strict";

/**
 * Updates fields on an existing Jira issue.
 *
 * PUT /rest/api/3/issue/{issueIdOrKey}
 * Body: { "fields": { "summary", "description", ... } }
 *
 * @param {object} params
 * @param {string} params.issueIdOrKey  - issue key ("PROJ-123") or numeric id
 * @param {string} [params.summary]     - new summary (omitted if undefined)
 * @param {string|object} [params.description] - plain text or ADF doc
 * @param {object} [params.extraFields] - any additional fields to set
 * @returns {Promise<{idOrKey: string, updated: boolean}>}
 */

const { createJiraClient } = require("../lib/jiraClient");
const { toAdfDescription } = require("../lib/adf");

async function updateIssue({ issueIdOrKey, summary, description, extraFields = {} }) {
  if (!issueIdOrKey) throw new Error("updateIssue: issueIdOrKey is required");

  const fields = { ...extraFields };
  if (summary !== undefined) fields.summary = summary;
  if (description !== undefined && description !== null && description !== "") {
    fields.description = toAdfDescription(description);
  }

  const client = createJiraClient();
  await client.put(`/issue/${encodeURIComponent(issueIdOrKey)}`, { fields });

  return { idOrKey: issueIdOrKey, updated: true };
}

module.exports = { updateIssue };
