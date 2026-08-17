# railcall-jira-module

RailCall Jira module — a Node.js module that wraps the Jira REST API and plugs
into RailCall as governed, dry-run-first automation.

> **Current state:** environment setup + GitHub Codespaces compatibility for the
> RailCall Studio UI.

## Running RailCall Studio in a GitHub Codespace

RailCall Studio normally binds to `127.0.0.1:8799` and rejects non-loopback
`Origin`/`Host` headers (DNS-rebinding guard). In a Codespace your browser
reaches forwarded ports via `https://<codespace>-<port>.app.github.dev`, so the
Studio responds with `cross-origin blocked (loopback only)`.

### Option A — recommended: reverse-proxy shim (no RailCall modification)

A tiny dependency-free Node proxy rewrites `Host`/`Origin`/`Referer` back to
loopback before forwarding to the Studio, so RailCall's stock security guard
passes. This survives `railcall update` because RailCall itself is untouched.

```bash
chmod +x tools/start-railcall-codespace.sh
tools/start-railcall-codespace.sh
```

Then in VS Code's **Ports panel**, forward **8899** and click **Open in Browser**
(URL: `https://<codespace>-8899.app.github.dev`).

| Component | File | Port |
|-----------|------|------|
| Proxy (this repo) | `tools/railcall-studio-proxy.js` | `8899` |
| RailCall Studio (installed) | `~/.railcall/station/workbench/studio_server.py` | `8799` |

The proxy is plain Node (no `npm install` needed). Env overrides:
`RAILCALL_PROXY_PORT`, `RAILCALL_UPSTREAM_PORT`.

### Option B — one-off patch (applies to the local install only)

The Studio server's `_guard()` can be patched to allow Codespace domains
(`*.app.github.dev` / `*.githubpreview.dev`). This works directly on port 8799
but is **overwritten by `railcall update`**, so it is not reproducible.

### Option C — SSH tunnel (no code changes at all)

From your **local** machine (not inside the Codespace):

```bash
gh codespace ssh -- -L 8799:localhost:8799
```

Then open `http://localhost:8799` in your browser. The request arrives as
loopback, so the stock guard passes with zero modifications.

## RailCall CLI reference

```bash
railcall          # terminal dashboard (key, flows, commands)
railcall studio   # visual Studio in the browser
railcall doctor   # environment health
railcall demo     # 30-second golden path: build → signed receipt → verify
railcall build    # local compile + socket audit + receipt
railcall audit    # zero-retention structural audit + signed receipt
```

## Jira module — structure

A Node.js module wrapping the Jira Cloud REST API v3 (Basic Auth: email + API
token from the environment).

```
railcall-jira-module/
├── index.js                  # entry point — exports all handlers
├── module.json               # RailCall module manifest (what RailCall loads)
├── manifest.json             # same manifest, user-requested filename
├── auth/
│   └── jiraAuth.js           # reads JIRA_DOMAIN / JIRA_EMAIL / JIRA_API_TOKEN → Base64 token
├── lib/
│   ├── jiraClient.js         # shared axios client + error mapping (401/400/403/404/429)
│   └── adf.js                # plain-text → Atlassian Document Format (ADF)
├── handlers/
│   ├── createIssue.js        # POST  /rest/api/3/issue
│   ├── updateIssue.js        # PUT   /rest/api/3/issue/{issueIdOrKey}
│   ├── searchIssues.js       # POST  /rest/api/3/search/jql  (new JQL API)
│   └── transitionIssue.js    # POST  /rest/api/3/issue/{issueIdOrKey}/transitions
└── test/
    └── jira.test.js          # 12 tests against an in-process mock Jira API
```

### Usage

```js
const jira = require("./index.js");

// Create an issue (description is auto-converted to ADF)
const issue = await jira.createIssue({
  projectKey: "PROJ",
  summary: "Fix login bug",
  description: "Users cannot log in\n\nPlease fix.",
  issueType: "Bug",
});
// → { id, key: "PROJ-1", self }

// Update an issue by id/key
await jira.updateIssue({ issueIdOrKey: "PROJ-1", summary: "Renamed", description: "New text" });

// Search with JQL (new /search/jql API — token-based pagination, no `total`)
const { issues, count, nextPageToken, isLast } = await jira.searchIssues({
  jql: 'project = "PROJ" ORDER BY created DESC',
});
// → { issues: [...], count, nextPageToken, isLast }

// Transition to a new status (find transition ids via the /transitions endpoint)
await jira.transitionIssue({ issueIdOrKey: "PROJ-1", transitionId: 31 });
```

### Notes & gotchas (learned against a real Jira Cloud instance)

- **Search endpoint changed.** The legacy `GET /rest/api/3/search` was removed in
  2025 (Atlassian CHANGE-2046). This module uses `POST /rest/api/3/search/jql`.
  The new API returns `issues`, `nextPageToken`, and `isLast` — there is **no
  `total` count** and pagination is token-based, not `startAt`/`maxResults`.
- **Issue types are project-specific.** Jira Product Discovery projects (like
  the `MDP` project used in testing) only accept the **`Idea`** issue type —
  `Task`/`Bug` will fail with `400 issuetype: Specify a valid issue type`.
  Use `GET /rest/api/3/issue/createmeta?projectKeys=<KEY>` to list valid types.
- **Field-level errors are surfaced.** A 400 with `{ "errors": { "issuetype": "..." } }`
  is reported as `issuetype: Specify a valid issue type`, not a generic message.

### Running the tests

```bash
npm install
npm test        # 12 tests, no network needed (mock Jira server in-process)
npm run validate  # live check against your real Jira (needs .env)
```

## Environment variables (Jira)

| Variable | Purpose |
|----------|---------|
| `JIRA_DOMAIN` | Your Jira instance, e.g. `yourcompany.atlassian.net` |
| `JIRA_EMAIL` | Account email used with an API token |
| `JIRA_API_TOKEN` | API token from https://id.atlassian.com/manage-profile/security/api-tokens |