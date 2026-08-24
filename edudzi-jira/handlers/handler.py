"""railcall/jira v0.2.0 — governed Jira Cloud issue operations.

Credential entry `jira` (saved via Studio → Integrations):
    {
      "JIRA_DOMAIN": "yourcompany.atlassian.net",
      "JIRA_EMAIL": "you@example.com",
      "JIRA_API_TOKEN": "ATATT3..."
    }

Ten commands, one Basic-Auth token. All hit
https://<domain>/rest/api/3 with `Authorization: Basic <b64(email:token)>`.

Notes:
  - searchIssues uses POST /rest/api/3/search/jql (the legacy GET /search was
    removed in 2025 — Atlassian CHANGE-2046). Pagination is token-based:
    nextPageToken / isLast, no `total`.
  - updateIssue and assignUser use PUT /rest/api/3/issue/{key}(...). The runtime
    exposes no PUT helper, so they use urllib directly (stdlib only).
  - attachFile uses POST /rest/api/3/issue/{key}/attachments with a
    multipart/form-data body and the `X-Atlassian-Token: no-check` header.
    No upload helper is exposed, so it builds the body with stdlib urllib.
  - Every handler returns (output, artifact) — the shape the station's
    _flatten_module_result expects.
"""

import json
import base64
import urllib.request
import urllib.error
import urllib.parse


def _creds():
    """Load Jira credentials from the RailCall vault ONLY.

    Contest review round 1 flagged env-var credential reads (visible in
    `ps auxe`, dumped in core files) — auth must come from the vault,
    never from os.environ / os.getenv.
    """
    helpers = __rc_helpers__  # noqa: F821 (injected by the module loader)
    # The manifest declares the credential provider as "edudzi-jira",
    # so Studio saves the integration under that name. Try it first, then
    # fall back to the short "jira" name in case it was saved that way.
    entry = helpers["vault_get"]("edudzi-jira")
    if not isinstance(entry, dict):
        entry = helpers["vault_get"]("jira")
    domain = email = token = ""
    if isinstance(entry, dict):
        domain = str(entry.get("JIRA_DOMAIN") or entry.get("domain") or "").strip()
        email = str(entry.get("JIRA_EMAIL") or entry.get("email") or "").strip()
        token = str(entry.get("JIRA_API_TOKEN") or entry.get("api_token") or "").strip()

    if not domain or not email or not token:
        raise RuntimeError(
            "Jira credentials missing — configure the `edudzi-jira` integration "
            "(JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN) in Studio → Integrations."
        )
    return domain, email, token


def _base_url(domain):
    domain = domain.rstrip("/")
    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain
    return domain + "/rest/api/3"


def _auth_header(email, token):
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


def _parse(body):
    """Parse a response body (bytes) into JSON, tolerating empty bodies."""
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _fail(status, body):
    """Raise on HTTP >= 400 so API errors never masquerade as data.

    Contest review round 1: helper-based calls were discarding the status
    code, so a 401/400 error body flowed through and e.g. createIssue
    returned {"ok": True, "id": ""} on failure. Writes must fail loud.
    Field-level errors ({"errors": {"issuetype": "..."}}) are surfaced
    verbatim so agents can self-correct.
    """
    try:
        status = int(status)
    except (TypeError, ValueError):
        return
    if status < 400:
        return
    data = _parse(body)
    parts = []
    if isinstance(data, dict):
        field_errors = data.get("errors")
        if isinstance(field_errors, dict):
            parts += [f"{k}: {v}" for k, v in field_errors.items()]
        messages = data.get("errorMessages")
        if isinstance(messages, list):
            parts += [str(m) for m in messages]
        if not parts and data:
            parts.append(json.dumps(data)[:300])
    raise RuntimeError(f"Jira HTTP {status}: " + ("; ".join(parts) or "unknown error"))


def _request(method, path, payload=None):
    """Run an HTTP request against the Jira API.

    Uses the runtime's __rc_helpers__ HTTP helpers where available (POST/GET/
    DELETE/PATCH); PUT falls back to urllib since no PUT helper is exposed.
    Returns the parsed JSON body (dict/list) or {}.
    """
    helpers = __rc_helpers__  # noqa: F821
    domain, email, token = _creds()
    url = _base_url(domain) + path
    headers = {"Authorization": _auth_header(email, token)}

    if method == "POST":
        status, body = helpers["http_post_json"](url, payload or {}, timeout=20, headers=headers)
        _fail(status, body)
        return _parse(body)
    if method == "GET":
        status, body = helpers["http_get_json"](url, timeout=20, headers=headers)
        _fail(status, body)
        return _parse(body)
    if method == "DELETE":
        status, body = helpers["http_delete_json"](url, timeout=20, headers=headers)
        _fail(status, body)
        return _parse(body)
    if method == "PATCH":
        status, body = helpers["http_patch_json"](url, payload or {}, timeout=20, headers=headers)
        _fail(status, body)
        return _parse(body)
    if method == "PUT":
        # No PUT helper exposed — use stdlib urllib directly.
        data = json.dumps(payload or {}).encode("utf-8")
        hdrs = dict(headers)
        hdrs["Content-Type"] = "application/json"
        hdrs["Content-Length"] = str(len(data))
        req = urllib.request.Request(url, data=data, method="PUT", headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return _parse(resp.read())
        except urllib.error.HTTPError as e:
            err = b""
            try:
                err = e.read()[:400]
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code}: {err.decode('utf-8', errors='replace')}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"network error: {e.reason}")

    raise RuntimeError(f"unsupported method: {method}")


def _upload_multipart(path, file_name, file_bytes):
    """POST a multipart/form-data upload (used by attachFile).

    Builds the multipart body by hand with stdlib only — the runtime exposes no
    upload/multipart helper. Jira's attachments endpoint requires the
    `X-Atlassian-Token: no-check` header. Returns the parsed JSON body.
    """
    import uuid

    boundary = "----railcall" + uuid.uuid4().hex
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
    )
    body = header.encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    domain, email, token = _creds()
    url = _base_url(domain) + path
    headers = {
        "Authorization": _auth_header(email, token),
        "X-Atlassian-Token": "no-check",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _parse(resp.read())
    except urllib.error.HTTPError as e:
        err = b""
        try:
            err = e.read()[:400]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}: {err.decode('utf-8', errors='replace')}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"network error: {e.reason}")


def to_adf(description):
    """Convert plain text to Atlassian Document Format (ADF)."""
    if not description:
        return {"type": "doc", "version": 1, "content": []}
    if isinstance(description, dict) and description.get("type") == "doc":
        return description

    paragraphs = [p.strip() for p in str(description).split("\n\n") if p.strip()]
    content = [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]}
        for p in paragraphs
    ]
    if not content:
        content.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": content}


# ---------------------------------------------------------------------------
# Command handlers — RailCall calls each with (inputs, stamp) and expects a
# (output, artifact) tuple back.
# ---------------------------------------------------------------------------


def jira_createIssue(inputs, stamp):
    """Create a Jira issue."""
    project_key = (inputs.get("project_key") or "").strip()
    summary = (inputs.get("summary") or "").strip()
    if not project_key:
        raise RuntimeError("project_key is required")
    if not summary:
        raise RuntimeError("summary is required")

    issue_type = (inputs.get("issue_type") or "Task").strip() or "Task"
    fields = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    description = inputs.get("description")
    if description:
        fields["description"] = to_adf(description)

    data = _request("POST", "/issue", {"fields": fields})
    return {
        "ok": True,
        "id": data.get("id", ""),
        "key": data.get("key", ""),
        "self": data.get("self", ""),
    }, {"kind": "jira.createIssue"}


def jira_updateIssue(inputs, stamp):
    """Update a Jira issue's fields."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")

    fields = {}
    summary = inputs.get("summary")
    if summary:
        fields["summary"] = str(summary).strip()
    description = inputs.get("description")
    if description:
        fields["description"] = to_adf(description)
    if not fields:
        raise RuntimeError("nothing to update — provide summary and/or description")

    _request("PUT", f"/issue/{issue_id_or_key}", {"fields": fields})
    return {"ok": True, "id_or_key": issue_id_or_key, "updated": True}, {"kind": "jira.updateIssue"}


def jira_searchIssues(inputs, stamp):
    """Search Jira issues using JQL."""
    jql = (inputs.get("jql") or "").strip()
    if not jql:
        raise RuntimeError("jql is required")

    fields = inputs.get("fields") or ["summary", "status", "assignee"]
    max_results = int(inputs.get("max_results") or 50)
    payload = {"jql": jql, "fields": fields, "maxResults": max_results}
    next_page_token = inputs.get("next_page_token")
    if next_page_token:
        payload["nextPageToken"] = str(next_page_token)

    data = _request("POST", "/search/jql", payload)

    issues = []
    for issue in data.get("issues", []) or []:
        issues.append({
            "id": issue.get("id", ""),
            "key": issue.get("key", ""),
            "self": issue.get("self", ""),
            "fields": issue.get("fields", {}),
        })

    return {
        "ok": True,
        "issues": issues,
        "count": len(issues),
        "next_page_token": data.get("nextPageToken"),
        "is_last": data.get("isLast", True),
    }, {"kind": "jira.searchIssues"}


def jira_transitionIssue(inputs, stamp):
    """Transition a Jira issue to a new status."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    transition_id = (inputs.get("transition_id") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    if not transition_id:
        raise RuntimeError("transition_id is required")

    _request(
        "POST",
        f"/issue/{issue_id_or_key}/transitions",
        {"transition": {"id": transition_id}},
    )
    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "transition_id": transition_id,
    }, {"kind": "jira.transitionIssue"}


def jira_getIssue(inputs, stamp):
    """Get full details for a single Jira issue."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")

    fields = inputs.get("fields")
    path = f"/issue/{issue_id_or_key}"
    if fields:
        path += "?fields=" + ",".join(str(f) for f in fields)

    data = _request("GET", path)
    fields_data = data.get("fields", {}) or {}
    status = fields_data.get("status") or {}
    assignee = fields_data.get("assignee") or {}
    return {
        "ok": True,
        "id": data.get("id", ""),
        "key": data.get("key", ""),
        "self": data.get("self", ""),
        "summary": fields_data.get("summary"),
        "status": status.get("name") if isinstance(status, dict) else None,
        "assignee": assignee.get("displayName") if isinstance(assignee, dict) else None,
        "fields": fields_data,
    }, {"kind": "jira.getIssue"}


def jira_addComment(inputs, stamp):
    """Add a comment to a Jira issue."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    comment = (inputs.get("comment") or inputs.get("body") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    if not comment:
        raise RuntimeError("comment is required")

    data = _request("POST", f"/issue/{issue_id_or_key}/comment", {"body": to_adf(comment)})
    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "comment_id": data.get("id", ""),
        "self": data.get("self", ""),
        "created": data.get("created", ""),
    }, {"kind": "jira.addComment"}


def jira_assignUser(inputs, stamp):
    """Assign a Jira issue to a user (by accountId or email)."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    account_id = (inputs.get("account_id") or inputs.get("accountId") or "").strip()
    email = (inputs.get("email") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    if not account_id and not email:
        raise RuntimeError("assignee is required — provide account_id or email")

    if not account_id and email:
        # Resolve the user's accountId from their email via user search.
        results = _request(
            "GET",
            f"/user/search?query={urllib.parse.quote(email)}&maxResults=1",
        )
        if not isinstance(results, list) or not results:
            raise RuntimeError(f"no Jira user found for email: {email}")
        account_id = str(results[0].get("accountId") or "").strip()
        if not account_id:
            raise RuntimeError(f"could not resolve accountId for email: {email}")

    _request("PUT", f"/issue/{issue_id_or_key}/assignee", {"accountId": account_id})
    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "account_id": account_id,
    }, {"kind": "jira.assignUser"}


def jira_attachFile(inputs, stamp):
    """Upload a file (screenshot / document) to a Jira issue."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    file_name = (inputs.get("file_name") or inputs.get("filename") or "").strip()
    file_content = inputs.get("file_content") or inputs.get("content") or ""
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    if not file_name:
        raise RuntimeError("file_name is required")
    if not file_content:
        raise RuntimeError("file_content is required")

    if isinstance(file_content, str):
        if inputs.get("file_is_base64"):
            try:
                file_bytes = base64.b64decode(file_content)
            except Exception as e:
                raise RuntimeError(f"file_content is not valid base64: {e}")
        else:
            file_bytes = file_content.encode("utf-8")
    else:
        file_bytes = bytes(file_content)

    data = _upload_multipart(f"/issue/{issue_id_or_key}/attachments", file_name, file_bytes)
    attachments = []
    for a in data if isinstance(data, list) else []:
        attachments.append({
            "id": a.get("id", ""),
            "filename": a.get("filename", ""),
            "mimeType": a.get("mimeType", ""),
            "content": a.get("content", ""),
            "size": a.get("size"),
        })
    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "attachments": attachments,
        "count": len(attachments),
    }, {"kind": "jira.attachFile"}


def jira_deleteIssue(inputs, stamp):
    """Delete a Jira issue."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")

    path = f"/issue/{issue_id_or_key}"
    if inputs.get("delete_subtasks") or inputs.get("deleteSubtasks"):
        path += "?deleteSubtasks=true"

    _request("DELETE", path)
    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "deleted": True,
    }, {"kind": "jira.deleteIssue"}


def jira_listIssueTypes(inputs, stamp):
    """List all issue types available in Jira."""
    data = _request("GET", "/issuetype")
    issue_types = []
    for t in data if isinstance(data, list) else []:
        issue_types.append({
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "subtask": t.get("subtask", False),
            "iconUrl": t.get("iconUrl", ""),
        })
    return {
        "ok": True,
        "issue_types": issue_types,
        "count": len(issue_types),
    }, {"kind": "jira.listIssueTypes"}


# ---------------------------------------------------------------------------
# Discovery commands — fill the gaps that blocked our own writes (Round 2:
# transitionIssue needs a transition id, but nothing listed valid ids).
# ---------------------------------------------------------------------------


def jira_getTransitions(inputs, stamp):
    """List valid transitions for an issue (ids usable by transitionIssue)."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")

    data = _request("GET", f"/issue/{issue_id_or_key}/transitions")
    transitions = []
    for t in data.get("transitions", []) or []:
        to_status = t.get("to") or {}
        transitions.append({
            "id": str(t.get("id", "")),
            "name": t.get("name", ""),
            "to_status": to_status.get("name", "") if isinstance(to_status, dict) else "",
        })
    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "transitions": transitions,
        "count": len(transitions),
    }, {"kind": "jira.getTransitions"}


def jira_listProjects(inputs, stamp):
    """List Jira projects accessible to the credential's account."""
    data = _request("GET", "/project/search?maxResults=100")
    rows = data.get("values", []) if isinstance(data, dict) else (data or [])
    projects = []
    for p in rows if isinstance(rows, list) else []:
        projects.append({
            "id": str(p.get("id", "")),
            "key": p.get("key", ""),
            "name": p.get("name", ""),
            "style": p.get("style", ""),
        })
    return {
        "ok": True,
        "projects": projects,
        "count": len(projects),
    }, {"kind": "jira.listProjects"}


def jira_getProjectIssueTypes(inputs, stamp):
    """List valid issue types for one project (createmeta)."""
    project_key = (inputs.get("project_key") or "").strip()
    if not project_key:
        raise RuntimeError("project_key is required")

    data = _request(
        "GET",
        f"/issue/createmeta/{urllib.parse.quote(project_key)}/issuetypes",
    )
    rows = data.get("issueTypes") or data.get("values") or []
    issue_types = []
    for t in rows if isinstance(rows, list) else []:
        issue_types.append({
            "id": str(t.get("id", "")),
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "subtask": t.get("subtask", False),
        })
    return {
        "ok": True,
        "project_key": project_key,
        "issue_types": issue_types,
        "count": len(issue_types),
    }, {"kind": "jira.getProjectIssueTypes"}


# ---------------------------------------------------------------------------
# Composite commands — several API calls under ONE approval (the pattern that
# scored highest in marketplace Round 2). Writes inside a composite are never
# retried; a mid-sequence failure raises loudly and says which steps landed.
# ---------------------------------------------------------------------------


def jira_triageIssue(inputs, stamp):
    """Composite: fetch an issue, post a triage comment, optionally transition."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    comment = (inputs.get("comment") or "").strip()
    transition_id = (inputs.get("transition_id") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    if not comment:
        raise RuntimeError("comment is required")

    # Step 1 — read context.
    try:
        issue = jira_getIssue({"issue_id_or_key": issue_id_or_key}, stamp)[0]
    except RuntimeError as e:
        raise RuntimeError(f"triageIssue failed at getIssue (nothing written): {e}")

    # Step 2 — comment.
    try:
        commented = jira_addComment(
            {"issue_id_or_key": issue_id_or_key, "comment": comment}, stamp
        )[0]
    except RuntimeError as e:
        raise RuntimeError(f"triageIssue: issue fetched, but addComment failed: {e}")

    # Step 3 — optional transition.
    transitioned = False
    if transition_id:
        try:
            jira_transitionIssue(
                {"issue_id_or_key": issue_id_or_key, "transition_id": transition_id},
                stamp,
            )
            transitioned = True
        except RuntimeError as e:
            raise RuntimeError(
                f"triageIssue: issue fetched and comment {commented.get('comment_id', '')!r} "
                f"posted, but transition failed: {e}"
            )

    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "summary": issue.get("summary"),
        "status_before": issue.get("status"),
        "assignee": issue.get("assignee"),
        "comment_id": commented.get("comment_id", ""),
        "transitioned": transitioned,
        "transition_id": transition_id or None,
    }, {"kind": "jira.triageIssue"}


def jira_resolveWithNote(inputs, stamp):
    """Composite: add a closing note and transition in one approval."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    comment = (inputs.get("comment") or "").strip()
    transition_id = (inputs.get("transition_id") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    if not comment:
        raise RuntimeError("comment is required")
    if not transition_id:
        raise RuntimeError("transition_id is required (discover ids via jira.getTransitions)")

    try:
        commented = jira_addComment(
            {"issue_id_or_key": issue_id_or_key, "comment": comment}, stamp
        )[0]
    except RuntimeError as e:
        raise RuntimeError(f"resolveWithNote failed at addComment (nothing written): {e}")

    try:
        jira_transitionIssue(
            {"issue_id_or_key": issue_id_or_key, "transition_id": transition_id}, stamp
        )
    except RuntimeError as e:
        raise RuntimeError(
            f"resolveWithNote: comment {commented.get('comment_id', '')!r} posted, "
            f"but transition failed: {e}"
        )

    return {
        "ok": True,
        "id_or_key": issue_id_or_key,
        "comment_id": commented.get("comment_id", ""),
        "transition_id": transition_id,
        "resolved": True,
    }, {"kind": "jira.resolveWithNote"}


def jira_cloneIssue(inputs, stamp):
    """Composite: copy an issue into a new one (summary, description, type)."""
    issue_id_or_key = (inputs.get("issue_id_or_key") or "").strip()
    if not issue_id_or_key:
        raise RuntimeError("issue_id_or_key is required")
    project_key = (inputs.get("project_key") or "").strip()
    suffix = str(inputs.get("summary_suffix") or " (clone)")

    try:
        source = jira_getIssue({"issue_id_or_key": issue_id_or_key}, stamp)[0]
    except RuntimeError as e:
        raise RuntimeError(f"cloneIssue failed at getIssue (nothing created): {e}")

    src_fields = source.get("fields") or {}
    summary = str(source.get("summary") or "").strip()
    if not summary:
        raise RuntimeError(f"source issue {issue_id_or_key} has no summary to clone")
    issuetype = (src_fields.get("issuetype") or {}).get("name") if isinstance(
        src_fields.get("issuetype"), dict
    ) else None

    # Target project: explicit override, else the source issue's project.
    target_project = project_key
    if not target_project:
        proj = src_fields.get("project")
        target_project = proj.get("key", "") if isinstance(proj, dict) else ""

    create_inputs = {
        "project_key": target_project,
        "summary": summary + suffix,
        "description": src_fields.get("description") or "",
    }
    if not create_inputs["project_key"]:
        raise RuntimeError(
            "could not determine source project — pass project_key explicitly"
        )
    if issuetype:
        create_inputs["issue_type"] = issuetype

    try:
        created = jira_createIssue(create_inputs, stamp)[0]
    except RuntimeError as e:
        raise RuntimeError(f"cloneIssue: source read OK, but createIssue failed: {e}")

    return {
        "ok": True,
        "cloned_from": issue_id_or_key,
        "id": created.get("id", ""),
        "key": created.get("key", ""),
        "self": created.get("self", ""),
    }, {"kind": "jira.cloneIssue"}


def jira_bulkTransitionFromJql(inputs, stamp):
    """Composite: transition every issue matching a JQL (per-issue outcomes).

    The search failing raises loudly. Individual transition failures are
    reported per issue (never retried, never swallowed silently) so one bad
    issue doesn't hide the other results.
    """
    jql = (inputs.get("jql") or "").strip()
    transition_id = (inputs.get("transition_id") or "").strip()
    if not jql:
        raise RuntimeError("jql is required")
    if not transition_id:
        raise RuntimeError("transition_id is required (discover ids via jira.getTransitions)")
    try:
        max_results = int(inputs.get("max_results") or 50)
    except (TypeError, ValueError):
        max_results = 50
    max_results = max(1, min(max_results, 200))

    data = _request(
        "POST",
        "/search/jql",
        {"jql": jql, "fields": ["status"], "maxResults": max_results},
    )
    keys = [
        str(i.get("key", "")).strip()
        for i in (data.get("issues", []) or [])
        if str(i.get("key", "")).strip()
    ]

    transitioned, failed = [], []
    for k in keys:
        try:
            _request(
                "POST",
                f"/issue/{k}/transitions",
                {"transition": {"id": transition_id}},
            )
            transitioned.append(k)
        except RuntimeError as e:
            failed.append({"key": k, "error": str(e)[:300]})

    return {
        "ok": True,
        "jql": jql,
        "transition_id": transition_id,
        "matched": len(keys),
        "transitioned_count": len(transitioned),
        "failed_count": len(failed),
        "transitioned": transitioned,
        "failed": failed,
    }, {"kind": "jira.bulkTransitionFromJql"}
