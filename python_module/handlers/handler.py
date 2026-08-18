"""railcall/jira v0.1.0 — governed Jira Cloud issue operations.

Credential entry `jira` (saved via Studio → Integrations):
    {
      "JIRA_DOMAIN": "yourcompany.atlassian.net",
      "JIRA_EMAIL": "you@example.com",
      "JIRA_API_TOKEN": "ATATT3..."
    }

Four commands, one Basic-Auth token. All hit
https://<domain>/rest/api/3 with `Authorization: Basic <b64(email:token)>`.

Notes:
  - searchIssues uses POST /rest/api/3/search/jql (the legacy GET /search was
    removed in 2025 — Atlassian CHANGE-2046). Pagination is token-based:
    nextPageToken / isLast, no `total`.
  - updateIssue uses PUT /rest/api/3/issue/{key}. The runtime exposes no PUT
    helper, so it uses urllib directly (stdlib only).
  - Every handler returns (output, artifact) — the shape the station's
    _flatten_module_result expects.
"""

import os
import json
import base64
import urllib.request
import urllib.error


def _creds():
    """Load Jira credentials from the vault (fall back to env vars)."""
    helpers = __rc_helpers__  # noqa: F821 (injected by the module loader)
    # The manifest declares the credential provider as "zakirhossen23-jira",
    # so Studio saves the integration under that name. Try it first, then
    # fall back to the short "jira" name in case it was saved that way.
    entry = helpers["vault_get"]("zakirhossen23-jira")
    if not isinstance(entry, dict):
        entry = helpers["vault_get"]("jira")
    if isinstance(entry, dict):
        domain = str(entry.get("JIRA_DOMAIN") or entry.get("domain") or "").strip()
        email = str(entry.get("JIRA_EMAIL") or entry.get("email") or "").strip()
        token = str(entry.get("JIRA_API_TOKEN") or entry.get("api_token") or "").strip()
    else:
        domain = email = token = ""

    if not domain:
        domain = os.getenv("JIRA_DOMAIN", "").strip()
    if not email:
        email = os.getenv("JIRA_EMAIL", "").strip()
    if not token:
        token = os.getenv("JIRA_API_TOKEN", "").strip()

    if not domain or not email or not token:
        raise RuntimeError(
            "Jira credentials missing — configure the `jira` integration "
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
        return _parse(body)
    if method == "GET":
        status, body = helpers["http_get_json"](url, timeout=20, headers=headers)
        return _parse(body)
    if method == "DELETE":
        status, body = helpers["http_delete_json"](url, timeout=20, headers=headers)
        return _parse(body)
    if method == "PATCH":
        status, body = helpers["http_patch_json"](url, payload or {}, timeout=20, headers=headers)
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
