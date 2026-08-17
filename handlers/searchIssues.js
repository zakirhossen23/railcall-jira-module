"use strict";

/**
 * Searches Jira issues with a JQL query.
 *
 * POST /rest/api/3/search/jql   (the legacy GET /rest/api/3/search was removed
 * in 2025 — see https://developer.atlassian.com/changelog/#CHANGE-2046)
 * Body: { jql, fields, maxResults, nextPageToken }
 *
 * NOTE: the new JQL search API no longer returns a `total` count or
 * `startAt`/`maxResults`. Pagination is token-based via `nextPageToken`, and
 * `isLast` tells you whether more pages exist.
 *
 * @param {object} params
 * @param {string} params.jql        - the JQL query, e.g. 'project = "PROJ" ORDER BY created DESC'
 * @param {string[]} [params.fields] - fields to return (default: summary, status, assignee)
 * @param {number} [params.maxResults=50] - max issues to return
 * @param {string} [params.nextPageToken] - pagination token from a previous call
 * @returns {Promise<{issues: Array, nextPageToken: string|null, isLast: boolean, count: number}>}
 */

const { createJiraClient } = require("../lib/jiraClient");

const DEFAULT_FIELDS = ["summary", "status", "assignee"];

async function searchIssues({ jql, fields = DEFAULT_FIELDS, maxResults = 50, nextPageToken }) {
  if (!jql) throw new Error("searchIssues: jql is required");

  const client = createJiraClient();
  const { data } = await client.post("/search/jql", {
    jql,
    fields,
    maxResults,
    ...(nextPageToken ? { nextPageToken } : {}),
  });

  const issues = (data.issues || []).map((issue) => ({
    id: issue.id,
    key: issue.key,
    self: issue.self,
    fields: issue.fields,
  }));

  return {
    issues,
    count: issues.length,
    nextPageToken: data.nextPageToken || null,
    isLast: data.isLast !== false,
  };
}

module.exports = { searchIssues };
