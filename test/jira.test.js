"use strict";

/**
 * Handler tests — run against an in-process mock Jira REST API so no network
 * or real credentials are needed. Verifies request shapes, the Basic Auth
 * header, ADF conversion, response mapping, and error handling (401/400/404).
 */

const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");

// ---- in-process mock Jira server -------------------------------------------
const requests = [];
let server;

before(async () => {
  server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const parsedBody = body ? JSON.parse(body) : undefined;
      requests.push({
        method: req.method,
        url: req.url,
        auth: req.headers.authorization || "",
        body: parsedBody,
      });

      const send = (status, payload) => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(payload));
      };

      // POST /issue -> create
      if (req.method === "POST" && req.url === "/rest/api/3/issue") {
        // If the payload has an invalid issuetype, return a field-level 400.
        if (parsedBody && parsedBody.fields && parsedBody.fields.issuetype && parsedBody.fields.issuetype.name === "Nope") {
          return send(400, {
            errorMessages: [],
            errors: { issuetype: "Specify a valid issue type" },
          });
        }
        return send(201, { id: "10001", key: "PROJ-1", self: "https://mock/rest/api/3/issue/10001" });
      }
      // PUT /issue/{id} -> update
      if (req.method === "PUT" && /^\/rest\/api\/3\/issue\/[^/]+$/.test(req.url)) {
        return send(204, {});
      }
      // POST /search/jql -> search (new endpoint; legacy GET /search is removed)
      if (req.method === "POST" && req.url === "/rest/api/3/search/jql") {
        return send(200, {
          issues: [
            { id: "10001", key: "PROJ-1", self: "x", fields: { summary: "First", status: { name: "To Do" } } },
            { id: "10002", key: "PROJ-2", self: "x", fields: { summary: "Second", status: { name: "In Progress" } } },
          ],
          nextPageToken: "abc123",
          isLast: false,
        });
      }
      // POST /issue/{id}/transitions -> transition
      if (req.method === "POST" && /\/transitions$/.test(req.url)) {
        return send(204, {});
      }
      // Any other authed API call -> 401 (exercises error mapping)
      if (req.url.startsWith("/rest/api/3/")) {
        return send(401, { errorMessages: ["Bad credentials"] });
      }
      return send(404, { errorMessages: ["no route"] });
    });
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  // Point the module at the mock (read at request time by jiraAuth).
  // http:// scheme is respected by jiraAuth so local testing needs no TLS.
  process.env.JIRA_DOMAIN = `http://127.0.0.1:${port}`;
  process.env.JIRA_EMAIL = "tester@example.com";
  process.env.JIRA_API_TOKEN = "mock-token";
});

after(() => {
  server.close();
});

// ---- handlers ----------------------------------------------------------------
const { createIssue } = require("../handlers/createIssue");
const { updateIssue } = require("../handlers/updateIssue");
const { searchIssues } = require("../handlers/searchIssues");
const { transitionIssue } = require("../handlers/transitionIssue");
const { buildAuthorizationHeader } = require("../auth/jiraAuth");

const EXPECTED_AUTH = `Basic ${Buffer.from("tester@example.com:mock-token").toString("base64")}`;

test("createIssue posts to /issue and returns id/key", async () => {
  const result = await createIssue({
    projectKey: "PROJ",
    summary: "Fix the login bug",
    description: "Users cannot log in\n\nPlease fix.",
    issueType: "Bug",
  });

  assert.deepEqual(result, { id: "10001", key: "PROJ-1", self: "https://mock/rest/api/3/issue/10001" });

  const req = requests.at(-1);
  assert.equal(req.method, "POST");
  assert.equal(req.url, "/rest/api/3/issue");
  assert.equal(req.auth, EXPECTED_AUTH);

  // ADF conversion
  assert.equal(req.body.fields.project.key, "PROJ");
  assert.equal(req.body.fields.summary, "Fix the login bug");
  assert.equal(req.body.fields.issuetype.name, "Bug");
  assert.equal(req.body.fields.description.type, "doc");
  assert.equal(req.body.fields.description.content.length, 2); // two paragraphs
  assert.equal(req.body.fields.description.content[0].content[0].text, "Users cannot log in");
});

test("createIssue requires projectKey and summary", async () => {
  await assert.rejects(() => createIssue({ summary: "x" }), /projectKey is required/);
  await assert.rejects(() => createIssue({ projectKey: "PROJ" }), /summary is required/);
});

test("updateIssue PUTs to /issue/{key} with only provided fields", async () => {
  const result = await updateIssue({ issueIdOrKey: "PROJ-1", summary: "Renamed" });
  assert.deepEqual(result, { idOrKey: "PROJ-1", updated: true });

  const req = requests.at(-1);
  assert.equal(req.method, "PUT");
  assert.equal(req.url, "/rest/api/3/issue/PROJ-1");
  assert.equal(req.body.fields.summary, "Renamed");
  assert.equal(req.body.fields.description, undefined); // not sent
});

test("updateIssue requires issueIdOrKey", async () => {
  await assert.rejects(() => updateIssue({ summary: "x" }), /issueIdOrKey is required/);
});

test("searchIssues POSTs to /search/jql and maps issues", async () => {
  const result = await searchIssues({ jql: 'project = "PROJ"' });

  assert.equal(result.count, 2);
  assert.equal(result.issues.length, 2);
  assert.equal(result.issues[0].key, "PROJ-1");
  assert.equal(result.issues[1].fields.status.name, "In Progress");
  assert.equal(result.nextPageToken, "abc123");
  assert.equal(result.isLast, false);

  const req = requests.at(-1);
  assert.equal(req.method, "POST");
  assert.equal(req.url, "/rest/api/3/search/jql");
  assert.equal(req.body.jql, 'project = "PROJ"');
  assert.equal(req.body.maxResults, 50);
  assert.deepEqual(req.body.fields, ["summary", "status", "assignee"]);
});

test("searchIssues requires jql", async () => {
  await assert.rejects(() => searchIssues({}), /jql is required/);
});

test("transitionIssue POSTs to /transitions with transition id", async () => {
  const result = await transitionIssue({ issueIdOrKey: "PROJ-1", transitionId: 31 });
  assert.deepEqual(result, { idOrKey: "PROJ-1", transitionId: 31 });

  const req = requests.at(-1);
  assert.equal(req.method, "POST");
  assert.equal(req.url, "/rest/api/3/issue/PROJ-1/transitions");
  assert.equal(req.body.transition.id, "31");
});

test("transitionIssue requires transitionId", async () => {
  await assert.rejects(() => transitionIssue({ issueIdOrKey: "PROJ-1" }), /transitionId is required/);
});

test("auth builds the correct Basic token", () => {
  assert.equal(buildAuthorizationHeader(), EXPECTED_AUTH);
});

test("a 401 response becomes a clear error message", async () => {
  // Force the mock to 401 for a path the real module would use differently:
  // use an unhandled-but-authed route via the search path trick is awkward,
  // so instead assert the interceptor logic on a bespoke request.
  const { createJiraClient } = require("../lib/jiraClient");
  const client = createJiraClient();
  await assert.rejects(() => client.get("/nonexistent"), /401 Unauthorized.*JIRA_EMAIL/s);
});

test("field-level Jira errors (400) surface the offending field", async () => {
  // The mock returns 401 for unknown authed routes; simulate a 400 with a
  // field-level `errors` object via a dedicated route on the mock.
  const { createJiraClient } = require("../lib/jiraClient");
  const client = createJiraClient();
  // Point at a path the mock treats as a 400-with-errors: add a route below.
  await assert.rejects(
    () => client.post("/issue", { fields: { issuetype: { name: "Nope" } } }),
    /issuetype: Specify a valid issue type/
  );
});

test("missing env vars throw with the variable names", () => {
  const { getJiraConfig } = require("../auth/jiraAuth");
  const saved = { ...process.env };
  delete process.env.JIRA_DOMAIN;
  delete process.env.JIRA_EMAIL;
  delete process.env.JIRA_API_TOKEN;
  assert.throws(() => getJiraConfig(), /JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN/);
  Object.assign(process.env, saved);
});
