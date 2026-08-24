# edudzi-jira — RailCall Jira module

A Python module for [RailCall](https://railcall.ai) that wraps the **Jira Cloud
REST API v3**. Seventeen commands — create, update, search, transition, comment,
assign, attach, delete, and read issues, plus multi-step composites — all
governed by RailCall's dry-run-first, approval-gated automation.

**Install and use in ~5 minutes.**

## What you get

| Command | What it does | Risk |
|---------|--------------|------|
| `jira.createIssue` | Create an issue (plain text → ADF) | medium |
| `jira.updateIssue` | Update summary / description | medium |
| `jira.searchIssues` | JQL search (new `/search/jql` API) | low |
| `jira.transitionIssue` | Move an issue to a new status | medium |
| `jira.getIssue` | Fetch issue details | low |
| `jira.addComment` | Add a comment | medium |
| `jira.assignUser` | Assign by accountId or email | medium |
| `jira.attachFile` | Upload a file attachment | medium |
| `jira.deleteIssue` | Delete an issue | high |
| `jira.listIssueTypes` | List instance-wide issue types | low |
| `jira.getTransitions` | List valid transitions + ids for an issue | low |
| `jira.listProjects` | List accessible projects | low |
| `jira.getProjectIssueTypes` | List valid types for one project | low |
| `jira.triageIssue` | **Composite:** fetch context → comment → optional transition | medium |
| `jira.resolveWithNote` | **Composite:** closing note + transition in one approval | medium |
| `jira.cloneIssue` | **Composite:** copy an issue into a new one | medium |
| `jira.bulkTransitionFromJql` | **Composite:** transition every JQL match (per-issue outcomes) | high |

## Prerequisites

- **RailCall CLI** on your `PATH` — check with `railcall --version`
- **Python 3** (the handler uses only the standard library)
- A **Jira Cloud** instance and an **API token**:
  https://id.atlassian.com/manage-profile/security/api-tokens

## Install (2 minutes)

```bash
railcall market install edudzi/jira
```

the bundle — start it with `railcall studio` and click **Modules → Reload all**.

## Configure credentials (2 minutes)

In **Studio → Integrations**, add a credential entry named `jira`:

| Field | Example |
|-------|---------|
| `JIRA_DOMAIN` | `yourcompany.atlassian.net` |
| `JIRA_EMAIL` | `you@example.com` |
| `JIRA_API_TOKEN` | `ATATT3...` |

Credentials are read from the RailCall vault **only** — never from process
environment variables (vault reads keep tokens out of `ps auxe` and core dumps).
The handler looks up `edudzi-jira` first, then `jira`.

## Verify (1 minute) (*Optional*)

```bash
railcall doctor          # environment health
railcall demo            # golden path: build → signed receipt → verify
```

In Studio → Modules, `edudzi-jira` should show **loaded** with 17 commands.

## Use it (2 minutes)

Run any `jira.*` command from the RailCall dashboard. Writes are
approval-gated — you preview the payload, then approve.

Example — create an issue:

| Input | Value |
|-------|-------|
| `project_key` | `PROJ` |
| `summary` | `Fix login bug` |
| `issue_type` | `Bug` |

Output: `{ "id": "10001", "key": "PROJ-1", "self": "https://..." }`

## How it works

- Basic Auth: `Authorization: Basic <b64(email:token)>` against
  `https://<domain>/rest/api/3`.
- The runtime injects `__rc_helpers__` (`http_post_json`, `http_get_json`,
  `http_delete_json`, `http_patch_json`, `vault_get`). PUT and multipart uploads
  have no runtime helper, so they use stdlib `urllib`.
- Every handler returns `(output, artifact)` — the shape the station's
  `_flatten_module_result` expects.

## Notes & gotchas

- **Search endpoint changed.** The legacy `GET /rest/api/3/search` was removed in
  2025 (Atlassian CHANGE-2046). This module uses `POST /rest/api/3/search/jql` —
  token-based pagination (`nextPageToken` / `isLast`), no `total`.
- **Issue types are project-specific.** Jira Product Discovery projects (like
  `MDP`) only accept the `Idea` type — `Task`/`Bug` fail with
  `400 issuetype: Specify a valid issue type`. Use
  `GET /rest/api/3/issue/createmeta?projectKeys=<KEY>` to list valid types.
- **Field-level errors are surfaced.** A 400 with
  `{ "errors": { "issuetype": "..." } }` is reported as
  `issuetype: Specify a valid issue type`, not a generic message.
- **File uploads** need the `X-Atlassian-Token: no-check` header and a
  `multipart/form-data` body — built by hand with stdlib `urllib`.


## Uninstall

```bash
rm -rf ~/.railcall/station/modules/edudzi-jira
```

## Repository layout

```
edudzi-jira/
├── manifest.json        # RailCall module manifest (what RailCall loads)
├── module.json          # same manifest, duplicate copy
├── module.sig           # Ed25519 signature over the bundle (v2 tree)
├── requirements.txt     # no external deps — stdlib only
├── handlers/
│   ├── __init__.py
│   └── handler.py       # all 17 command handlers + shared helpers
└── test/
    ├── __init__.py
    └── test_jira.py     # 63 unit tests — all 17 handlers + helpers
```

## Companion workflows

`edudzi-jira` is designed to work alongside other RailCall modules:

| Module | Pairing |
|--------|---------|
| `edudzi/jira` + **Slack module** | Triage alert in Slack → `jira_createIssue` opens a ticket; `jira_addComment` posts updates back |
| `edudzi/jira` + **GitHub module** | `jira_cloneIssue` links PRs to tickets; `jira_resolveWithNote` closes issues when PRs merge |
| `edudzi/jira` + **PagerDuty module** | Incident fires → `jira_createIssue` with high priority → `jira_assignUser` routes to on-call |
| `edudzi/jira` + **Notion/Confluence module** | Sprint planning in Notion → `jira_bulkTransitionFromJql` moves issues in batch |
| `edudzi/jira` + **GitHub Actions module** | CI fails → webhook → `jira_addComment` with failure logs on the linked ticket |

Example triage workflow:

```
1.  Slack alert fires (#incidents channel)
2.  AI agent runs jira_getProjectIssueTypes → picks "Incident"
3.  jira_createIssue creates a high-priority incident ticket
4.  jira_assignUser routes it to the on-call engineer
5.  jira_triageIssue adds a triage note + moves to "In Progress"
6.  When resolved: jira_resolveWithNote closes the loop
```

## Platform bug report

**Bug: tree manifest excludes `test/` from signature — tests are unsigned.**

After adding `edudzi-jira/test/` (with `__init__.py` + `test_jira.py`), running
`railcall market module sign` and `railcall market module verify` still reports
**7 files** in the tree manifest — the same count as before the test files were
added. This means the `test/` directory is **outside the signed tree**.

**Impact:** A malicious actor (or a compromised build) could replace test files
without invalidating the module signature. If tests are published alongside the
module (via `tests_url`), a reviewer seeing a passing test badge would have no
assurance the tests on disk match what was signed.

**Reproduction:**

```bash
# In the edudzi-jira/ directory:
railcall market module sign edudzi-jira
railcall market module verify edudzi-jira
#   → reports "7 files" even though edudzi-jira/test/ contains 2 files
```

**Expected behavior:** Either `module sign` should include `test/` in the tree
manifest (9 files), or `module verify` should warn when `tests_url` is declared
but the test directory is unsigned.

**Suggested fix:** In the signing logic, expand the file-walk to include `test/`
by default (or document which directories are included/excluded in the v2 tree
spec). If the intent is to exclude tests, `module verify` should emit a warning
when `tests_url` is present in the manifest.