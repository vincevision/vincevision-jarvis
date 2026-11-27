"""Offline tests for the Cloud Integrations Pack (Google + Notion).

No network and no Google/Notion SDKs required: every external call is
faked. We exercise parsing, formatting, payload construction and the voice
action routing for each agent.
"""

import base64

import pytest

from actions import google_auth, gmail_agent, calendar_agent, docs_agent, drive_agent, notion_agent


# ── generic fake Google service ─────────────────────────────────────────────

class FakeCall:
    def __init__(self, result=None, recorder=None, name=""):
        self._result = result if result is not None else {}
        self._recorder = recorder
        self._name = name

    def execute(self):
        if self._recorder is not None:
            self._recorder.append(self._name)
        return self._result


class FakeMessages:
    def __init__(self, rec):
        self.rec = rec
        self.sent = []

    def list(self, **kw):
        self.rec.append(("list", kw))
        return FakeCall({"messages": [{"id": "m1"}, {"id": "m2"}]})

    def get(self, **kw):
        self.rec.append(("get", kw))
        return FakeCall({
            "id": kw.get("id"),
            "payload": {"headers": [
                {"name": "From", "value": "boss@acme.com"},
                {"name": "Subject", "value": "Engagement kickoff"},
                {"name": "Date", "value": "Thu, 27 Nov 2026"},
            ], "mimeType": "text/plain",
                "body": {"data": base64.urlsafe_b64encode(b"Hello sir").decode()}},
        })

    def send(self, **kw):
        self.sent.append(kw)
        self.rec.append(("send", kw))
        return FakeCall({"id": "sent1"})


class FakeUsers:
    def __init__(self, rec):
        self._messages = FakeMessages(rec)
        self.rec = rec

    def messages(self):
        return self._messages

    def labels(self):
        return self

    def list(self, **kw):
        return FakeCall({"labels": [{"name": "INBOX"}, {"name": "Work"}]})


class FakeGmailService:
    def __init__(self):
        self.rec = []
        self._users = FakeUsers(self.rec)

    def users(self):
        return self._users


# ── google_auth ─────────────────────────────────────────────────────────────

def test_google_setup_instructions_mention_secret():
    text = google_auth.setup_instructions()
    assert "google_client_secret.json" in text
    assert "console.cloud.google.com" in text


def test_google_is_configured_false(tmp_path, monkeypatch):
    monkeypatch.setattr(google_auth, "CLIENT_SECRET_PATH", tmp_path / "nope.json")
    assert google_auth.is_configured() is False


def test_google_is_configured_true(tmp_path, monkeypatch):
    secret = tmp_path / "google_client_secret.json"
    secret.write_text("{}")
    monkeypatch.setattr(google_auth, "CLIENT_SECRET_PATH", secret)
    assert google_auth.is_configured() is True


def test_google_status_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(google_auth, "CLIENT_SECRET_PATH", tmp_path / "nope.json")
    assert "not connected" in google_auth.status()


def test_google_logout_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(google_auth, "TOKEN_PATH", tmp_path / "tok.json")
    assert "No Google token" in google_auth.logout()


def test_google_auth_agent_setup():
    out = google_auth.google_auth_agent({"action": "setup"})
    assert "google_client_secret.json" in out


def test_google_auth_agent_unknown():
    assert "connect google" in google_auth.google_auth_agent({"action": "bogus"})


# ── gmail ───────────────────────────────────────────────────────────────────

def test_gmail_decode_body_plain():
    payload = {"mimeType": "text/plain",
               "body": {"data": base64.urlsafe_b64encode(b"Hi there").decode()}}
    assert gmail_agent._decode_body(payload) == "Hi there"


def test_gmail_decode_body_multipart():
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b"<b>x</b>").decode()}},
        {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"plain").decode()}},
    ]}
    assert gmail_agent._decode_body(payload) == "plain"


def test_gmail_headers_lowercase():
    msg = {"payload": {"headers": [{"name": "Subject", "value": "Test"}]}}
    assert gmail_agent._headers(msg)["subject"] == "Test"


def test_gmail_unread_action(monkeypatch):
    fake = FakeGmailService()
    monkeypatch.setattr(gmail_agent, "_service", lambda: fake)
    out = gmail_agent.gmail_agent({"action": "unread"})
    assert "boss@acme.com" in out
    assert "Engagement kickoff" in out


def test_gmail_send_action(monkeypatch):
    fake = FakeGmailService()
    monkeypatch.setattr(gmail_agent, "_service", lambda: fake)
    out = gmail_agent.gmail_agent({"action": "send", "to": "a@b.com",
                                   "subject": "Hi", "body": "Body"})
    assert "sent" in out.lower()
    assert fake._users._messages.sent, "send should have been called"
    raw = fake._users._messages.sent[0]["body"]["raw"]
    decoded = base64.urlsafe_b64decode(raw).decode()
    assert "a@b.com" in decoded and "Body" in decoded


def test_gmail_send_requires_to(monkeypatch):
    monkeypatch.setattr(gmail_agent, "_service", lambda: FakeGmailService())
    out = gmail_agent.gmail_agent({"action": "send"})
    assert "to" in out.lower()


def test_gmail_read_action(monkeypatch):
    monkeypatch.setattr(gmail_agent, "_service", lambda: FakeGmailService())
    out = gmail_agent.gmail_agent({"action": "read", "id": "m1"})
    assert "Hello sir" in out and "Engagement kickoff" in out


def test_gmail_unconfigured_returns_setup(monkeypatch):
    def boom():
        raise RuntimeError(google_auth.setup_instructions())
    monkeypatch.setattr(gmail_agent, "_service", boom)
    out = gmail_agent.gmail_agent({"action": "unread"})
    assert "google_client_secret.json" in out


# ── calendar ────────────────────────────────────────────────────────────────

def test_calendar_parse_when_datetime():
    start, end = calendar_agent.parse_when("2026-11-28T15:00:00", 60)
    assert start["dateTime"].startswith("2026-11-28T15:00")
    assert end["dateTime"].startswith("2026-11-28T16:00")


def test_calendar_parse_when_space_separator():
    start, _ = calendar_agent.parse_when("2026-11-28 15:00")
    assert "2026-11-28T15:00" in start["dateTime"]


def test_calendar_parse_when_all_day():
    start, end = calendar_agent.parse_when("2026-11-28")
    assert start == {"date": "2026-11-28"}
    assert end == {"date": "2026-11-29"}


def test_calendar_parse_when_invalid():
    assert calendar_agent.parse_when("not a date") is None
    assert calendar_agent.parse_when("") is None


def test_calendar_format_event():
    ev = {"summary": "Standup", "start": {"dateTime": "2026-11-28T09:00:00+03:00"},
          "location": "Office"}
    line = calendar_agent.format_event(ev)
    assert "Standup" in line and "Office" in line and "2026-11-28 09:00" in line


class FakeEvents:
    def __init__(self, rec):
        self.rec = rec

    def insert(self, **kw):
        self.rec.append(("insert", kw))
        return FakeCall({"id": "e1", "htmlLink": "https://cal/e1",
                         "summary": kw["body"]["summary"]})

    def list(self, **kw):
        self.rec.append(("list", kw))
        return FakeCall({"items": [
            {"summary": "Pentest kickoff", "start": {"dateTime": "2026-11-28T10:00:00+03:00"}}]})

    def delete(self, **kw):
        self.rec.append(("delete", kw))
        return FakeCall({})


class FakeCalendarService:
    def __init__(self):
        self.rec = []
        self._events = FakeEvents(self.rec)

    def events(self):
        return self._events


def test_calendar_create_event(monkeypatch):
    fake = FakeCalendarService()
    monkeypatch.setattr(calendar_agent, "_service", lambda: fake)
    out = calendar_agent.create_event("Kickoff", "2026-11-28T10:00:00")
    assert "created" in out and "Kickoff" in out
    body = fake.rec[0][1]["body"]
    assert body["start"]["timeZone"] == "Africa/Nairobi"


def test_calendar_create_bad_time(monkeypatch):
    monkeypatch.setattr(calendar_agent, "_service", lambda: FakeCalendarService())
    out = calendar_agent.create_event("X", "whenever")
    assert "couldn't parse" in out


def test_calendar_today_action(monkeypatch):
    monkeypatch.setattr(calendar_agent, "_service", lambda: FakeCalendarService())
    out = calendar_agent.calendar_agent({"action": "today"})
    assert "Pentest kickoff" in out and "TODAY" in out


def test_calendar_create_action_missing_fields(monkeypatch):
    monkeypatch.setattr(calendar_agent, "_service", lambda: FakeCalendarService())
    out = calendar_agent.calendar_agent({"action": "create"})
    assert "title and a start time" in out


def test_calendar_delete_action(monkeypatch):
    fake = FakeCalendarService()
    monkeypatch.setattr(calendar_agent, "_service", lambda: fake)
    out = calendar_agent.calendar_agent({"action": "delete", "id": "e1"})
    assert "deleted" in out


# ── docs ────────────────────────────────────────────────────────────────────

def test_docs_extract_text():
    doc = {"body": {"content": [
        {"paragraph": {"elements": [{"textRun": {"content": "Line one\n"}}]}},
        {"paragraph": {"elements": [{"textRun": {"content": "Line two\n"}}]}},
    ]}}
    assert docs_agent.extract_text(doc) == "Line one\nLine two"


def test_docs_end_index():
    doc = {"body": {"content": [{"endIndex": 42}]}}
    assert docs_agent._end_index(doc) == 41
    assert docs_agent._end_index({"body": {"content": []}}) == 1


class FakeDocuments:
    def __init__(self, rec):
        self.rec = rec

    def create(self, **kw):
        self.rec.append(("create", kw))
        return FakeCall({"documentId": "doc1"})

    def batchUpdate(self, **kw):
        self.rec.append(("batchUpdate", kw))
        return FakeCall({})

    def get(self, **kw):
        self.rec.append(("get", kw))
        return FakeCall({"title": "My Doc", "body": {"content": [
            {"paragraph": {"elements": [{"textRun": {"content": "Hello\n"}}]}},
            {"endIndex": 7}]}})


class FakeDocsService:
    def __init__(self):
        self.rec = []
        self._documents = FakeDocuments(self.rec)

    def documents(self):
        return self._documents


def test_docs_create(monkeypatch):
    fake = FakeDocsService()
    monkeypatch.setattr(docs_agent, "_service", lambda: fake)
    out = docs_agent.create_doc("Report", "Some text")
    assert "doc1" in out and "created" in out
    assert any(c[0] == "batchUpdate" for c in fake.rec)


def test_docs_append(monkeypatch):
    fake = FakeDocsService()
    monkeypatch.setattr(docs_agent, "_service", lambda: fake)
    out = docs_agent.append_text("doc1", "more text")
    assert "Appended" in out


def test_docs_read_action(monkeypatch):
    monkeypatch.setattr(docs_agent, "_service", lambda: FakeDocsService())
    out = docs_agent.docs_agent({"action": "read", "id": "doc1"})
    assert "My Doc" in out and "Hello" in out


def test_docs_export_report(monkeypatch):
    fake = FakeDocsService()
    monkeypatch.setattr(docs_agent, "_service", lambda: fake)
    # export_report imports _gather from report_agent at call time
    import actions.report_agent as ra
    monkeypatch.setattr(ra, "_gather", lambda: ([], {"targets": []}))
    out = docs_agent.export_report(client="Acme")
    assert "created" in out and "doc1" in out
    created = [c for c in fake.rec if c[0] == "create"]
    assert "Acme" in created[0][1]["body"]["title"]


# ── drive ───────────────────────────────────────────────────────────────────

def test_drive_fmt_file():
    line = drive_agent._fmt_file({"name": "report.md", "id": "f1", "size": "120"})
    assert "report.md" in line and "f1" in line and "120 bytes" in line


class FakeFiles:
    def __init__(self, rec):
        self.rec = rec

    def list(self, **kw):
        self.rec.append(("list", kw))
        return FakeCall({"files": [{"name": "report.md", "id": "f1", "size": "10"}]})

    def create(self, **kw):
        self.rec.append(("create", kw))
        return FakeCall({"id": "f2", "name": kw["body"]["name"],
                         "webViewLink": "https://drive/f2"})

    def get(self, **kw):
        return FakeCall({"name": "report.md"})

    def get_media(self, **kw):
        self.rec.append(("get_media", kw))
        return FakeCall({})


class FakeDriveService:
    def __init__(self):
        self.rec = []
        self._files = FakeFiles(self.rec)

    def files(self):
        return self._files


def test_drive_list_action(monkeypatch):
    monkeypatch.setattr(drive_agent, "_service", lambda: FakeDriveService())
    out = drive_agent.drive_agent({"action": "list"})
    assert "report.md" in out and "DRIVE" in out


def test_drive_search_action(monkeypatch):
    fake = FakeDriveService()
    monkeypatch.setattr(drive_agent, "_service", lambda: fake)
    out = drive_agent.drive_agent({"action": "search", "query": "report"})
    assert "report.md" in out
    q = fake.rec[0][1]["q"]
    assert "name contains 'report'" in q


def test_drive_upload_missing_file(monkeypatch):
    monkeypatch.setattr(drive_agent, "_service", lambda: FakeDriveService())
    out = drive_agent.drive_agent({"action": "upload", "path": "/no/such/file.txt"})
    assert "doesn't exist" in out


def test_drive_upload_action(tmp_path, monkeypatch):
    f = tmp_path / "report.md"
    f.write_text("# report")
    fake = FakeDriveService()
    monkeypatch.setattr(drive_agent, "_service", lambda: fake)
    # MediaFileUpload comes from googleapiclient which isn't installed; fake it
    import sys as _sys, types as _types
    http_mod = _types.ModuleType("googleapiclient.http")
    http_mod.MediaFileUpload = lambda *a, **k: object()
    parent = _types.ModuleType("googleapiclient")
    parent.http = http_mod
    monkeypatch.setitem(_sys.modules, "googleapiclient", parent)
    monkeypatch.setitem(_sys.modules, "googleapiclient.http", http_mod)
    out = drive_agent.drive_agent({"action": "upload", "path": str(f)})
    assert "Uploaded" in out and "report.md" in out


# ── notion ──────────────────────────────────────────────────────────────────

def test_notion_text_blocks_split():
    blocks = notion_agent._text_blocks("x" * 4000)
    assert len(blocks) == 3  # 1900 + 1900 + 200
    assert all(b["type"] == "paragraph" for b in blocks)


def test_notion_text_blocks_empty():
    blocks = notion_agent._text_blocks("")
    assert len(blocks) == 1


def test_notion_unconfigured_request(tmp_path, monkeypatch):
    monkeypatch.setattr(notion_agent, "CONFIG_PATH", tmp_path / "notion.json")
    with pytest.raises(RuntimeError):
        notion_agent._request("POST", "/search", {})


def test_notion_setup_saves_config(tmp_path, monkeypatch):
    cfg = tmp_path / "notion.json"
    monkeypatch.setattr(notion_agent, "CONFIG_PATH", cfg)
    out = notion_agent.notion_agent({"action": "setup", "token": "ntn_abc",
                                     "parent_page_id": "p1"})
    assert "connected" in out
    import json
    saved = json.loads(cfg.read_text())
    assert saved["token"] == "ntn_abc" and saved["parent_page_id"] == "p1"


def test_notion_status_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(notion_agent, "CONFIG_PATH", tmp_path / "notion.json")
    assert "not connected" in notion_agent.notion_agent({"action": "status"})


def test_notion_create_page(monkeypatch):
    monkeypatch.setattr(notion_agent, "_load_config",
                        lambda: {"token": "t", "parent_page_id": "p1"})
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"url": "https://notion.so/page1"}

    monkeypatch.setattr(notion_agent, "_request", fake_request)
    out = notion_agent.create_page("My Page", "content here")
    assert "created" in out and "notion.so" in out
    method, path, payload = calls[0]
    assert method == "POST" and path == "/pages"
    assert payload["parent"]["page_id"] == "p1"


def test_notion_create_page_no_parent(monkeypatch):
    monkeypatch.setattr(notion_agent, "_load_config", lambda: {"token": "t"})
    out = notion_agent.create_page("X")
    assert "parent page id" in out


def test_notion_search(monkeypatch):
    monkeypatch.setattr(notion_agent, "_load_config", lambda: {"token": "t"})

    def fake_request(method, path, payload=None):
        return {"results": [{"id": "r1", "object": "page", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Runbook"}]}}}]}

    monkeypatch.setattr(notion_agent, "_request", fake_request)
    out = notion_agent.search("runbook")
    assert "Runbook" in out and "r1" in out


def test_notion_sync_findings_to_database(monkeypatch):
    monkeypatch.setattr(notion_agent, "_load_config",
                        lambda: {"token": "t", "database_id": "db1"})
    import actions.findings_agent as fa
    monkeypatch.setattr(fa, "list_findings", lambda limit=1000: [
        {"title": "SQLi", "severity": "critical", "status": "open",
         "target": "api.acme.com", "cvss": 9.8}])
    calls = []
    monkeypatch.setattr(notion_agent, "_request",
                        lambda m, p, payload=None: calls.append((m, p, payload)) or {})
    out = notion_agent.sync_findings()
    assert "Synced 1 findings" in out
    assert calls[0][2]["parent"]["database_id"] == "db1"
    assert calls[0][2]["properties"]["Severity"]["select"]["name"] == "Critical"


def test_notion_sync_findings_empty(monkeypatch):
    import actions.findings_agent as fa
    monkeypatch.setattr(fa, "list_findings", lambda limit=1000: [])
    assert "No findings" in notion_agent.sync_findings()


def test_notion_sync_findings_page_fallback(monkeypatch):
    monkeypatch.setattr(notion_agent, "_load_config",
                        lambda: {"token": "t", "parent_page_id": "p1"})
    import actions.findings_agent as fa
    monkeypatch.setattr(fa, "list_findings", lambda limit=1000: [
        {"title": "XSS", "severity": "high", "status": "open"}])
    monkeypatch.setattr(fa, "summary", lambda: {"total": 1, "open": 1})
    monkeypatch.setattr(notion_agent, "_request",
                        lambda m, p, payload=None: {"url": "https://notion.so/x"})
    out = notion_agent.sync_findings()
    assert "created" in out
