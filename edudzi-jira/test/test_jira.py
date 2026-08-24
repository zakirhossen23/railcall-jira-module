"""Unit tests for edudzi-jira handlers — zero network, no credentials needed.

Run:  python -m pytest edudzi-jira/test/test_jira.py -v
   or: cd edudzi-jira && python -m pytest test/test_jira.py -v

Every test mocks __rc_helpers__ (the runtime injection) so the handler
never calls a real HTTP client or vault.  Tests cover all 17 commands,
the _fail() error-surfacing helper, and the to_adf() converter.
"""

import base64
import json
import os
import sys
import types
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure the handler module is importable even though it lives inside
# edudzi-jira/handlers/ and references __rc_helpers__ as a bare global.
# ---------------------------------------------------------------------------
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, "handlers"
)
sys.path.insert(0, os.path.abspath(_MODULE_DIR))

# We must pre-inject __rc_helpers__ into builtins so the handler module
# can reference it at import time (the loader does this at runtime).
_FAKE_HELPERS = {}
import builtins
builtins.__rc_helpers__ = _FAKE_HELPERS  # noqa: E402

import handler as h  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers — mock __rc_helpers__ for tests
# ---------------------------------------------------------------------------

def _make_helpers():
    """Return a fresh mock __rc_helpers__ dict with a fake vault entry."""
    vault = {
        "edudzi-jira": {
            "JIRA_DOMAIN": "test.atlassian.net",
            "JIRA_EMAIL": "test@example.com",
            "JIRA_API_TOKEN": "FAKE-TOKEN-123",
        }
    }

    def vault_get(key):
        return vault.get(key)

    last_request = {}  # captures the most recent HTTP call

    def http_post_json(url, payload=None, timeout=20, headers=None):
        last_request.update(
            method="POST", url=url, payload=payload, headers=headers
        )
        return (200, json.dumps(payload).encode())

    def http_get_json(url, timeout=20, headers=None):
        last_request.update(method="GET", url=url, headers=headers)
        # Return a default body; individual tests override this.
        return (200, json.dumps({}).encode())

    def http_delete_json(url, timeout=20, headers=None):
        last_request.update(method="DELETE", url=url, headers=headers)
        return (200, b"{}")

    def http_patch_json(url, payload=None, timeout=20, headers=None):
        last_request.update(
            method="PATCH", url=url, payload=payload, headers=headers
        )
        return (200, b"{}")

    return {
        "vault_get": vault_get,
        "http_post_json": http_post_json,
        "http_get_json": http_get_json,
        "http_delete_json": http_delete_json,
        "http_patch_json": http_patch_json,
        "_last_request": last_request,
        "_vault": vault,
    }


# ===========================================================================
# Unit tests — helpers
# ===========================================================================


class TestCreds(unittest.TestCase):
    """_creds() reads the vault, never os.environ."""

    def test_vault_lookup(self):
        builtins.__rc_helpers__ = _make_helpers()
        domain, email, token = h._creds()
        self.assertEqual(domain, "test.atlassian.net")
        self.assertEqual(email, "test@example.com")
        self.assertEqual(token, "FAKE-TOKEN-123")

    def test_missing_credentials_raises(self):
        helpers = _make_helpers()
        helpers["vault_get"] = lambda key: None
        builtins.__rc_helpers__ = helpers
        with self.assertRaises(RuntimeError):
            h._creds()


class TestBaseUrl(unittest.TestCase):
    def test_bare_domain(self):
        self.assertEqual(h._base_url("acme.atlassian.net"),
                         "https://acme.atlassian.net/rest/api/3")

    def test_strips_trailing_slash(self):
        self.assertEqual(h._base_url("https://acme.atlassian.net/"),
                         "https://acme.atlassian.net/rest/api/3")

    def test_already_has_scheme(self):
        self.assertEqual(
            h._base_url("https://acme.atlassian.net"),
            "https://acme.atlassian.net/rest/api/3",
        )


class TestAuthHeader(unittest.TestCase):
    def test_encoding(self):
        header = h._auth_header("alice@x.com", "tok123")
        raw = base64.b64decode(header.removeprefix("Basic "))
        self.assertEqual(raw, b"alice@x.com:tok123")


class TestParse(unittest.TestCase):
    def test_valid_json(self):
        body = json.dumps({"a": 1}).encode()
        self.assertEqual(h._parse(body), {"a": 1})

    def test_empty_body(self):
        self.assertEqual(h._parse(b""), {})
        self.assertEqual(h._parse(None), {})

    def test_invalid_json(self):
        self.assertEqual(h._parse(b"not json"), {})


class TestFail(unittest.TestCase):
    """_fail() should raise on HTTP >= 400, silent on success."""

    def test_success_no_raise(self):
        h._fail(200, b'{"ok": true}')

    def test_400_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            h._fail(400, json.dumps({
                "errors": {"issuetype": "Specify a valid issue type"}
            }).encode())
        self.assertIn("issuetype", str(ctx.exception))
        self.assertIn("Specify a valid issue type", str(ctx.exception))

    def test_401_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            h._fail(401, json.dumps({"errorMessages": ["Unauthorized"]}).encode())
        self.assertIn("Unauthorized", str(ctx.exception))

    def test_error_messages_list(self):
        with self.assertRaises(RuntimeError) as ctx:
            h._fail(400, json.dumps({
                "errorMessages": ["Issue does not exist", "Unknown project"]
            }).encode())
        msg = str(ctx.exception)
        self.assertIn("Issue does not exist", msg)
        self.assertIn("Unknown project", msg)

    def test_non_dict_body(self):
        with self.assertRaises(RuntimeError):
            h._fail(500, b"Internal Server Error")

    def test_none_status_silent(self):
        """Non-numeric status (e.g. from a broken helper) should not raise."""
        h._fail(None, b"{}")


class TestToAdf(unittest.TestCase):
    def test_empty(self):
        doc = h.to_adf("")
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(doc["content"], [])

    def test_single_paragraph(self):
        doc = h.to_adf("Hello world")
        self.assertEqual(len(doc["content"]), 1)
        self.assertEqual(doc["content"][0]["type"], "paragraph")
        self.assertEqual( 
            doc["content"][0]["content"][0]["text"], "Hello world"
        )

    def test_multi_paragraph(self):
        doc = h.to_adf("Para one\n\nPara two")
        self.assertEqual(len(doc["content"]), 2)

    def test_passthrough_adf(self):
        existing = {"type": "doc", "version": 1, "content": []}
        self.assertIs(h.to_adf(existing), existing)


# ===========================================================================
# Handler integration tests — each handler with a mocked __rc_helpers__
# ===========================================================================


class _HandlerTestBase(unittest.TestCase):
    """Base: sets up __rc_helpers__ + provides convenience methods."""

    def setUp(self):
        self.helpers = _make_helpers()
        builtins.__rc_helpers__ = self.helpers
        self.stamp = "test-stamp"

    def _last(self):
        return self.helpers["_last_request"]

    def _set_response(self, status=200, body=None):
        """Patch the helpers to return a specific status + body on next call."""
        if body is None:
            body = {}
        body_bytes = json.dumps(body).encode() if isinstance(body, dict) else body
        for key in (
            "http_post_json", "http_get_json", "http_delete_json",
            "http_patch_json",
        ):
            self.helpers[key] = lambda *a, _s=status, _b=body_bytes, **kw: (
                _s, _b,
            )


class TestCreateIssue(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            200,
            json.dumps({"id": "10001", "key": "TEST-1",
                         "self": "https://jira/test/10001"}).encode(),
        )
        out, art = h.jira_createIssue(
            {"project_key": "TEST", "summary": "Fix bug"}, self.stamp
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["key"], "TEST-1")
        self.assertEqual(art["kind"], "jira.createIssue")

    def test_missing_project_key(self):
        with self.assertRaises(RuntimeError):
            h.jira_createIssue({"summary": "Fix bug"}, self.stamp)

    def test_missing_summary(self):
        with self.assertRaises(RuntimeError):
            h.jira_createIssue({"project_key": "TEST"}, self.stamp)


class TestUpdateIssue(_HandlerTestBase):
    def test_happy_path(self):
        """PUT uses urllib — must mock urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("handler.urllib.request.urlopen", return_value=mock_resp):
            out, art = h.jira_updateIssue(
                {"issue_id_or_key": "TEST-1", "summary": "Renamed"},
                self.stamp,
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["id_or_key"], "TEST-1")

    def test_no_fields_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_updateIssue({"issue_id_or_key": "TEST-1"}, self.stamp)

    def test_missing_key_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_updateIssue({"summary": "x"}, self.stamp)


class TestSearchIssues(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            200,
            json.dumps({
                "issues": [
                    {"id": "1", "key": "TEST-1", "self": "x",
                     "fields": {"summary": "Hello"}},
                ],
                "nextPageToken": "abc",
                "isLast": False,
            }).encode(),
        )
        out, art = h.jira_searchIssues(
            {"jql": 'project = "TEST"'}, self.stamp
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["next_page_token"], "abc")
        self.assertFalse(out["is_last"])

    def test_empty_jql_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_searchIssues({}, self.stamp)


class TestTransitionIssue(_HandlerTestBase):
    def test_happy_path(self):
        out, art = h.jira_transitionIssue(
            {"issue_id_or_key": "TEST-1", "transition_id": "31"}, self.stamp
        )
        self.assertTrue(out["ok"])

    def test_missing_key(self):
        with self.assertRaises(RuntimeError):
            h.jira_transitionIssue({"transition_id": "31"}, self.stamp)

    def test_missing_transition(self):
        with self.assertRaises(RuntimeError):
            h.jira_transitionIssue({"issue_id_or_key": "TEST-1"}, self.stamp)


class TestGetIssue(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "id": "10001",
                "key": "TEST-1",
                "self": "x",
                "fields": {
                    "summary": "Fix login",
                    "status": {"name": "Open"},
                    "assignee": {"displayName": "Alice"},
                },
            }).encode(),
        )
        out, _ = h.jira_getIssue({"issue_id_or_key": "TEST-1"}, self.stamp)
        self.assertTrue(out["ok"])
        self.assertEqual(out["summary"], "Fix login")
        self.assertEqual(out["status"], "Open")
        self.assertEqual(out["assignee"], "Alice")

    def test_missing_key(self):
        with self.assertRaises(RuntimeError):
            h.jira_getIssue({}, self.stamp)


class TestAddComment(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            200,
            json.dumps({"id": "20001", "self": "x",
                         "created": "2026-01-01"}).encode(),
        )
        out, art = h.jira_addComment(
            {"issue_id_or_key": "TEST-1", "comment": "Looks good"}, self.stamp
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["comment_id"], "20001")

    def test_missing_comment(self):
        with self.assertRaises(RuntimeError):
            h.jira_addComment({"issue_id_or_key": "TEST-1"}, self.stamp)


class TestAssignUser(_HandlerTestBase):
    def test_by_account_id(self):
        """PUT uses urllib — must mock urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("handler.urllib.request.urlopen", return_value=mock_resp):
            out, _ = h.jira_assignUser(
                {"issue_id_or_key": "TEST-1", "account_id": "a1b2c3"},
                self.stamp,
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["account_id"], "a1b2c3")

    def test_by_email_resolves(self):
        """GET via helpers for email lookup, then PUT via urllib for assign."""
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps([{"accountId": "resolved-id-99"}]).encode(),
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("handler.urllib.request.urlopen", return_value=mock_resp):
            out, _ = h.jira_assignUser(
                {"issue_id_or_key": "TEST-1", "email": "user@example.com"},
                self.stamp,
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["account_id"], "resolved-id-99")

    def test_email_not_found_raises(self):
        self.helpers["http_get_json"] = lambda url, **kw: (200, b"[]")
        with self.assertRaises(RuntimeError):
            h.jira_assignUser(
                {"issue_id_or_key": "TEST-1", "email": "gone@example.com"},
                self.stamp,
            )

    def test_no_assignee_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_assignUser({"issue_id_or_key": "TEST-1"}, self.stamp)


class TestDeleteIssue(_HandlerTestBase):
    def test_happy_path(self):
        out, _ = h.jira_deleteIssue(
            {"issue_id_or_key": "TEST-1"}, self.stamp
        )
        self.assertTrue(out["ok"])

    def test_with_subtasks(self):
        out, _ = h.jira_deleteIssue(
            {"issue_id_or_key": "TEST-1", "delete_subtasks": True},
            self.stamp,
        )
        self.assertTrue(out["ok"])


class TestListIssueTypes(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps([
                {"id": "1", "name": "Task", "description": "A task",
                 "subtask": False, "iconUrl": "x"},
            ]).encode(),
        )
        out, _ = h.jira_listIssueTypes({}, self.stamp)
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["issue_types"][0]["name"], "Task")


class TestGetTransitions(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "transitions": [
                    {"id": "31", "name": "In Progress",
                     "to": {"name": "In Progress"}},
                    {"id": "41", "name": "Done",
                     "to": {"name": "Done"}},
                ]
            }).encode(),
        )
        out, _ = h.jira_getTransitions(
            {"issue_id_or_key": "TEST-1"}, self.stamp
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["transitions"][0]["id"], "31")

    def test_missing_key(self):
        with self.assertRaises(RuntimeError):
            h.jira_getTransitions({}, self.stamp)


class TestListProjects(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "values": [
                    {"id": "1", "key": "TEST", "name": "My Project",
                     "style": "next-gen"},
                ]
            }).encode(),
        )
        out, _ = h.jira_listProjects({}, self.stamp)
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["projects"][0]["key"], "TEST")


class TestGetProjectIssueTypes(_HandlerTestBase):
    def test_happy_path(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "issueTypes": [
                    {"id": "1", "name": "Bug", "description": "A bug",
                     "subtask": False},
                ]
            }).encode(),
        )
        out, _ = h.jira_getProjectIssueTypes(
            {"project_key": "TEST"}, self.stamp
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["project_key"], "TEST")
        self.assertEqual(out["count"], 1)

    def test_missing_project_key(self):
        with self.assertRaises(RuntimeError):
            h.jira_getProjectIssueTypes({}, self.stamp)


# ===========================================================================
# Composite handler tests
# ===========================================================================


class TestTriageIssue(_HandlerTestBase):
    def test_comment_only(self):
        # Mock getIssue
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "id": "1", "key": "TEST-1", "self": "x",
                "fields": {
                    "summary": "Bug",
                    "status": {"name": "Open"},
                    "assignee": None,
                },
            }).encode(),
        )
        # Mock addComment
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            200,
            json.dumps({"id": "20001", "self": "x", "created": "2026-01-01"}).encode(),
        )
        out, art = h.jira_triageIssue(
            {"issue_id_or_key": "TEST-1", "comment": "Triage note"},
            self.stamp,
        )
        self.assertTrue(out["ok"])
        self.assertFalse(out["transitioned"])

    def test_comment_and_transition(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "id": "1", "key": "TEST-1", "self": "x",
                "fields": {
                    "summary": "Bug", "status": {"name": "Open"},
                    "assignee": None,
                },
            }).encode(),
        )
        post_calls = []
        def mock_post(url, payload=None, **kw):
            post_calls.append(url)
            return (200, json.dumps({"id": "20001", "self": "x",
                                      "created": "2026-01-01"}).encode())
        self.helpers["http_post_json"] = mock_post
        out, _ = h.jira_triageIssue(
            {"issue_id_or_key": "TEST-1", "comment": "Done",
             "transition_id": "31"},
            self.stamp,
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["transitioned"])

    def test_transition_failure_reports_comment(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "id": "1", "key": "TEST-1", "self": "x",
                "fields": {
                    "summary": "Bug", "status": {"name": "Open"},
                    "assignee": None,
                },
            }).encode(),
        )
        def mock_post(url, payload=None, **kw):
            return (400, json.dumps({"errorMessages": ["Invalid transition"]}).encode())
        self.helpers["http_post_json"] = mock_post
        with self.assertRaises(RuntimeError) as ctx:
            h.jira_triageIssue(
                {"issue_id_or_key": "TEST-1", "comment": "Fail",
                 "transition_id": "99"},
                self.stamp,
            )
        msg = str(ctx.exception)
        # The error message should mention what succeeded before the failure.
        self.assertIn("addComment", msg)

    def test_missing_comment_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_triageIssue(
                {"issue_id_or_key": "TEST-1"}, self.stamp
            )


class TestResolveWithNote(_HandlerTestBase):
    def test_happy_path(self):
        post_calls = []
        def mock_post(url, payload=None, **kw):
            post_calls.append(url)
            return (200, json.dumps(
                {"id": "20001", "self": "x", "created": "2026-01-01"}
            ).encode())
        self.helpers["http_post_json"] = mock_post
        out, _ = h.jira_resolveWithNote(
            {"issue_id_or_key": "TEST-1", "comment": "Resolved",
             "transition_id": "31"},
            self.stamp,
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["resolved"])

    def test_missing_transition_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_resolveWithNote(
                {"issue_id_or_key": "TEST-1", "comment": "Done"},
                self.stamp,
            )

    def test_add_comment_fails_transition_not_called(self):
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            400,
            json.dumps({"errorMessages": ["Permission denied"]}).encode(),
        )
        with self.assertRaises(RuntimeError):
            h.jira_resolveWithNote(
                {"issue_id_or_key": "TEST-1", "comment": "Done",
                 "transition_id": "31"},
                self.stamp,
            )


class TestCloneIssue(_HandlerTestBase):
    def test_happy_path(self):
        get_called = []
        post_called = []

        def mock_get(url, **kw):
            get_called.append(url)
            return (200, json.dumps({
                "id": "1", "key": "TEST-1", "self": "x",
                "fields": {
                    "summary": "Original bug",
                    "description": {"type": "doc", "content": []},
                    "issuetype": {"name": "Bug"},
                    "project": {"key": "TEST"},
                },
            }).encode())

        def mock_post(url, payload=None, **kw):
            post_called.append(url)
            return (200, json.dumps({
                "id": "2", "key": "TEST-2", "self": "x",
            }).encode())

        self.helpers["http_get_json"] = mock_get
        self.helpers["http_post_json"] = mock_post
        out, art = h.jira_cloneIssue(
            {"issue_id_or_key": "TEST-1"}, self.stamp,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["key"], "TEST-2")
        self.assertEqual(out["cloned_from"], "TEST-1")
        self.assertEqual(len(get_called), 1)
        self.assertEqual(len(post_called), 1)

    def test_cross_project_clone(self):
        self.helpers["http_get_json"] = lambda url, **kw: (
            200,
            json.dumps({
                "id": "1", "key": "SRC-1", "self": "x",
                "fields": {
                    "summary": "Bug", "issuetype": {"name": "Bug"},
                    "project": {"key": "SRC"},
                },
            }).encode(),
        )
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            200,
            json.dumps({"id": "2", "key": "DST-1", "self": "x"}).encode(),
        )
        out, _ = h.jira_cloneIssue(
            {"issue_id_or_key": "SRC-1", "project_key": "DST"}, self.stamp
        )
        self.assertEqual(out["key"], "DST-1")


class TestBulkTransitionFromJql(_HandlerTestBase):
    def test_all_succeed(self):
        self.helpers["http_post_json"] = lambda url, payload=None, **kw: (
            200,
            json.dumps({
                "issues": [
                    {"key": "TEST-1"}, {"key": "TEST-2"}, {"key": "TEST-3"},
                ],
            }).encode(),
        )
        out, _ = h.jira_bulkTransitionFromJql(
            {"jql": 'project = "TEST"', "transition_id": "31"}, self.stamp
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["matched"], 3)
        self.assertEqual(out["transitioned_count"], 3)
        self.assertEqual(out["failed_count"], 0)

    def test_partial_failure(self):
        """Some transitions fail — per-issue outcomes reported."""
        post_count = [0]
        def mock_post(url, payload=None, **kw):
            post_count[0] += 1
            if post_count[0] == 1:
                # First call: search
                return (200, json.dumps({
                    "issues": [{"key": "TEST-1"}, {"key": "TEST-2"}],
                }).encode())
            elif post_count[0] == 2:
                # Second call: transition for TEST-1 — success
                return (200, b"{}")
            else:
                # Third call: transition for TEST-2 — fail
                return (400, json.dumps({
                    "errorMessages": ["Transition not valid"],
                }).encode())

        self.helpers["http_post_json"] = mock_post
        out, _ = h.jira_bulkTransitionFromJql(
            {"jql": 'project = "TEST"', "transition_id": "31"},
            self.stamp,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["matched"], 2)
        self.assertEqual(out["transitioned_count"], 1)
        self.assertEqual(out["failed_count"], 1)
        self.assertEqual(out["transitioned"], ["TEST-1"])
        self.assertEqual(out["failed"][0]["key"], "TEST-2")
        self.assertIn("Transition not valid", out["failed"][0]["error"])

    def test_empty_jql_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_bulkTransitionFromJql({}, self.stamp)

    def test_empty_transition_raises(self):
        with self.assertRaises(RuntimeError):
            h.jira_bulkTransitionFromJql({"jql": "project = X"}, self.stamp)


# ===========================================================================
# AttachFile (multipart upload path)
# ===========================================================================


class TestAttachFile(_HandlerTestBase):
    def test_happy_path_text(self):
        """Text file upload via multipart — mock urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{
            "id": "30001", "filename": "note.txt",
            "mimeType": "text/plain", "content": "https://x", "size": 5,
        }]).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("handler.urllib.request.urlopen", return_value=mock_resp):
            out, _ = h.jira_attachFile(
                {"issue_id_or_key": "TEST-1", "file_name": "note.txt",
                 "file_content": "hello"},
                self.stamp,
            )
            self.assertTrue(out["ok"])
            self.assertEqual(out["count"], 1)
            self.assertEqual(out["attachments"][0]["filename"], "note.txt")

    def test_missing_file_name(self):
        with self.assertRaises(RuntimeError):
            h.jira_attachFile(
                {"issue_id_or_key": "TEST-1", "file_content": "x"},
                self.stamp,
            )

    def test_missing_file_content(self):
        with self.assertRaises(RuntimeError):
            h.jira_attachFile(
                {"issue_id_or_key": "TEST-1", "file_name": "x.txt"},
                self.stamp,
            )


# ===========================================================================
# AttachFile HTTP error surfacing
# ===========================================================================


class TestAttachFileErrorSurfacing(_HandlerTestBase):
    def test_400_raises(self):
        """File upload 400 is surfaced, not swallowed."""
        http_err = urllib.error.HTTPError(
            url="https://x", code=400, msg="Bad Request",
            hdrs=None,
            fp=MagicMock(read=MagicMock(return_value=b'{"errorMessages":["File too big"]}')),
        )
        with patch("handler.urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(RuntimeError) as ctx:
                h.jira_attachFile(
                    {"issue_id_or_key": "TEST-1", "file_name": "big.zip",
                     "file_content": "x" * 100},
                    self.stamp,
                )
            self.assertIn("400", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
