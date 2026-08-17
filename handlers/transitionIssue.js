"use strict";

/**
 * Transitions an issue to a new status.
 *
 * POST /rest/api/3/issue/{issueIdOrKey}/transitions
 * Body: { "transition": { "id": "..." }, ...extra }
 *
 * Tip: find available transition ids with:
 *   GET /rest/api/3/issue/{issueIdOrKey}/transitions
 *
 * @param {object} params
 * @param {string} params.issueIdOrKey  - issue key ("PROJ-123") or numeric id
 * @param {string|number} params.transitionId - the transition id to apply
 * @param {object} [params.extra] - optional extra payload fields (e.g. fields to set on transition)
 * @returns {Promise<{idOrKey: string, transitionId: string|number}>}
 */

const { createJiraClient } = require("../lib/jiraClient");

async function transitionIssue({ issueIdOrKey, transitionId, extra = {} }) {
  if (!issueIdOrKey) throw new Error("transitionIssue: issueIdOrKey is required");
  if (transitionId === undefined || transitionId === null || transitionId === "") {
    throw new Error("transitionIssue: transitionId is required");
  }

  const client = createJiraClient();
  await client.post(
    `/issue/${encodeURIComponent(issueIdOrKey)}/transitions`,
    { transition: { id: String(transitionId) }, ...extra }
  );

  return { idOrKey: issueIdOrKey, transitionId };
}

module.exports = { transitionIssue };
