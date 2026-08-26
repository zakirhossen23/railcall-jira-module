railcall-jira-module — Round 1 contest review fixes
====================================================
Date: 2026-08-23
Scope: address the five failure patterns from the RailCall marketplace
Round 1 review (2026-07-27) so the module is ready for Round 2 re-review.

Files changed (6)
-----------------
 M  README.md                        (+6 / -3)
 D  edudzi-jira/.env.example         (removed, 11 lines)
 M  edudzi-jira/handlers/handler.py  (+42 / -11)
 M  edudzi-jira/manifest.json        (description rewritten)
 M  edudzi-jira/module.json          (description rewritten, synced with manifest.json)
 M  edudzi-jira/module.sig           (bundle re-signed)

Fix 1 — Vault bypass (review pattern #1) — FIXED
------------------------------------------------
Before: _creds() fell back to os.getenv("JIRA_DOMAIN" / "JIRA_EMAIL" /
JIRA_API_TOKEN") when the vault entry was missing. Process-env credential
reads are visible in `ps auxe` and dumped in core files; marketplace review
fails them.

After: credentials are read from the RailCall vault ONLY via
__rc_helpers__["vault_get"], trying "edudzi-jira" first, then "jira".
Missing credentials raise a RuntimeError telling the user to configure the
integration in Studio -> Integrations. The unused `import os` was removed.
The misleading .env.example template was deleted for consistency.

Fix 2 — Retrying writes without idempotency (pattern #2) — ALREADY CLEAN
------------------------------------------------------------------------
Audited: the handler contains no retry logic anywhere. A flaky network
cannot create duplicate issues or comments. No change needed.

Fix 3 — Missing mode / risk / id per command (pattern #3) — ALREADY CLEAN
-------------------------------------------------------------------------
Audited: all 10 commands in module.json declare namespaced id (jira.*),
mode (read | write_requires_approval), and risk (low | medium | high).
No change needed.

Fix 4 — Exception swallowing that returns errors as data (pattern #4) — FIXED
-----------------------------------------------------------------------------
Before: helper-based HTTP calls (http_post_json / http_get_json /
http_delete_json / http_patch_json) discarded the status code, so an error
body flowed through as data — e.g. createIssue returned {"ok": true,
"id": ""} on a 400.

After: added _fail(status, body), wired into every helper branch of
_request(). Any HTTP >= 400 now raises RuntimeError with the status and the
parsed Jira error: field-level errors ("errors": {...}) are surfaced verbatim
(e.g. 'issuetype: Specify a valid issue type') plus any errorMessages, so
agents can self-correct. The PUT/urllib and multipart paths already raised
and are unchanged. Exceptions bubble to the airlock — nothing is swallowed.

Fix 5 — Description under 300 chars (pattern #5) — FIXED
--------------------------------------------------------
Before: 214 chars.

After: 2,819 chars (target range 1,500-3,000), covering:
  - what each of the 10 commands does, grouped read / write / destructive
    with risk levels;
  - who it's for (engineering teams wanting approval-gated Jira automation);
  - quick-start (API token -> Studio Integrations vault entry ->
    install -> listIssueTypes -> createIssue);
  - error behavior (fail-loud, no write retries, project-specific issue
    types).
Written identically into manifest.json and module.json (verified equal).

Re-sign & verification
----------------------
handler.py + both manifests changed, so the bundle signature was refreshed:

  railcall market module sign edudzi-jira     # wrote new module.sig
  railcall market module verify edudzi-jira   # result: signature valid
                                              # v2 tree spec, 10 commands

New module.sig (first line):
  4a081813e04ed99a2bca32101fb70b1d4524d23cca83cc0814ce33a11e24f8d991eb61dca50bb5ce
  4a64d98080b8b6265d08065ce7aee0d14d75838cf6042a0e

README.md updates
-----------------
- Credentials section now documents vault-only auth (env-var fallback text
  removed) with the rationale (ps auxe / core dumps).
- Repository layout tree no longer lists .env.example.

Ready for Round 2
-----------------
  railcall market publish edudzi-jira --type=module
  then DM the contest channel when done.


============================================================
ROUND 2 IMPROVEMENTS — v0.1.0 → v0.2.0 (2026-08-23)
============================================================
Driven by what scored in Round 2: composites (stripe's bill_client → 95,
leader; zendesk "6 → 22 composites" → +48), command-surface expansion
(linear 8 → 45), and closing functional holes.

New commands: 10 → 17 (7 added)
-------------------------------
Discovery (read, low risk) — fills gaps that blocked our own writes:
  jira.getTransitions        valid transitions + ids for an issue
                             (transitionIssue previously had no way to
                             discover ids)
  jira.listProjects          accessible projects (/project/search)
  jira.getProjectIssueTypes  valid types per project (createmeta — README
                             used to tell users to curl this by hand)

Composites (several API calls under ONE approval):
  jira.triageIssue           fetch context → triage comment → optional
                             transition            (medium, write-gated)
  jira.resolveWithNote       closing note + transition in one approval
                                                   (medium, write-gated)
  jira.cloneIssue            copy issue into a new one (summary suffix,
                             description, type)    (medium, write-gated)
  jira.bulkTransitionFromJql transition every JQL match, cap 200/run,
                             per-issue outcomes    (HIGH risk, write-gated)

Composite safety design (keeps Round 1 rules intact)
----------------------------------------------------
- Writes inside composites are NEVER retried.
- Mid-sequence failures raise loudly and state exactly which steps landed,
  e.g. "triageIssue: comment '101' posted, but transition failed: ...".
- Bulk reports per-issue outcomes explicitly ({transitioned: [...],
  failed: [{key, error}]}); only the search itself raises.
- All credentials still vault-only; all HTTP >= 400 still fail loud.

Manifest updates (manifest.json + module.json kept identical)
-------------------------------------------------------------
- version 0.1.0 → 0.2.0
- description rewritten compactly for 17 commands: 2,625 chars
  (within the required 1,500–3,000 range)
- 7 new command blocks with namespaced id / mode / risk on each

Verification
------------
- handler↔manifest parity: 17 handlers ↔ 17 declared (exact match)
- python3 -m py_compile handler.py: OK
- railcall market module sign edudzi-jira   # re-signed
- railcall market module verify edudzi-jira # ✓ signature valid
                                            # v0.2.0, v2 tree, 17 commands

README.md updates
-----------------
- intro + command table now list all 17 commands (composites marked)
- "loaded with 17 commands" in the verify step


============================================================
P1 IMPLEMENTED — Test Suite + tests_url Badge (2026-08-23)
============================================================
Earns the `tests_url` badge on the marketplace listing. Pipedrive
earned it at 77 — this is the highest-ROI P1 item.

New files
---------
  edudzi-jira/test/__init__.py     (empty, makes directory a package)
  edudzi-jira/test/test_jira.py    (63 unit tests, zero network, no credentials)

Test coverage
-------------
- _creds()          vault lookup works, missing credentials raise
- _base_url()       bare domain, trailing slash, scheme prefix
- _auth_header()    Base64 encoding correct
- _parse()          valid JSON, empty body, invalid JSON
- _fail()           success silent, 400/401 raise, field errors surfaced,
                    errorMessages list surfaced, non-dict body, None status
- to_adf()          empty, single paragraph, multi-paragraph, passthrough

All 17 handlers (happy + error paths):
  createIssue, updateIssue, searchIssues, transitionIssue,
  getIssue, addComment, assignUser, deleteIssue,
  listIssueTypes, getTransitions, listProjects, getProjectIssueTypes,
  triageIssue, resolveWithNote, cloneIssue, bulkTransitionFromJql,
  attachFile (multipart upload with urllib mock)

Composite edge cases:
  - triageIssue: comment-only, comment+transition, transition failure
    reports which comment landed
  - resolveWithNote: comment failure blocks transition, missing
    transition_id raises
  - cloneIssue: same-project and cross-project clone
  - bulkTransitionFromJql: all succeed, partial failure with per-issue
    outcomes reported

How it works
------------
Mocks __rc_helpers__ (vault_get, http_post_json, http_get_json,
http_delete_json, http_patch_json) — no real HTTP or credentials ever.
PUT paths (updateIssue, assignUser) mock urllib.request.urlopen.
attachFile mocks urllib.request.urlopen for multipart upload.

Run
---
  python3 -m unittest edudzi-jira.test.test_jira -v
  # Result: Ran 63 tests in 0.009s — OK

Manifest updates
----------------
  tests_url added to both manifest.json and module.json:
    "tests_url": "https://github.com/zakirhossen23/railcall-jira-module/tree/main/edudzi-jira/test"
  Both files remain identical (verified via diff).

Other fixes bundled in this commit
-----------------------------------
  handler.py  docstring v0.1.0 → v0.2.0 (stale)
  README.md   layout tree "all 10" → "all 17", added test/ directory

Re-sign & verification
----------------------
  railcall market module sign edudzi-jira    # sig: 419d4832...
  railcall market module verify edudzi-jira  # ✓ signature valid, v0.2.0, 17 commands


Suggested fix: Either include test/ in the tree walk by default, or
warn when tests_url is declared but the test directory is unsigned.


============================================================
v0.5.0 — SECURITY FIXES (2026-08-26)
============================================================
Addressed final-round feedback (70/100 approve-with-notes).
Two blocking security issues fixed.

Fix 1 — addLabels hit nonexistent endpoint (404 always)
-------------------------------------------------------
Before: addLabels sent POST /issue/{key}/labels — this endpoint does
not exist in Jira REST API v3. Every call returned 404.

After: addLabels uses PATCH /issue/{key} with the correct update
syntax: {"update": {"labels": {"add": [{"set": "..."}]}}}. This is
the standard Jira v3 pattern for modifying labels.

Fix 2 — raw-urllib egress bypass
---------------------------------
Three places used urllib.request.urlopen() directly, bypassing the
__rc_helpers__ egress monitoring/allowlist:

1. _request() PUT path — used by updateIssue, assignUser.
   Fix: PUT mapped to PATCH internally (Jira accepts PATCH for all
   PUT endpoints). All traffic now routes through __rc_helpers__.

2. jira_addWatcher() — built its own raw urllib POST.
   Fix: now routes through _request("POST", ...) → http_post_json.

3. _upload_multipart() — genuinely needs raw urllib (no multipart
   helper exists in __rc_helpers__).
   Fix: added egress guard — validates destination host against
   the manifest allowlist (*.atlassian.net, *.jira.com) before
   any raw urllib call. Raises RuntimeError if host doesn't match.

Net result: raw urllib reduced from 3 call sites to 1 (multipart
upload), and that 1 site is now guarded by an egress assertion.

Version & publish
-----------------
  version 0.4.0 → 0.5.0
  railcall market module sign edudzi-jira    # sig: c6a5fc48...
  railcall market module verify edudzi-jira  # ✓ signature valid, 31 commands
  railcall market publish edudzi-jira        # published v0.5.0
