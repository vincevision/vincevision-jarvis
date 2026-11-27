"""Offline tests for the read-only local dashboard.

Rendering/routing are pure. One test spins up a real server on an ephemeral
port and talks to it over loopback — no external network.
"""

import json
import threading
import urllib.request

import pytest

from core import dashboard as db


@pytest.fixture
def summary():
    return {
        "health": {"python": "3.11.0", "version": "1.0", "api_key_configured": True,
                   "daemon_enabled": False, "directories": {"config": True},
                   "generated": "2026-11-27T10:00:00"},
        "findings": {"available": True,
                     "summary": {"total": 2},
                     "items": [{"id": 1, "title": "SQL injection", "severity": "critical",
                                "status": "open", "target": "api.acme.com", "cvss": 9.8},
                               {"id": 2, "title": "Open port", "severity": "low",
                                "status": "open", "target": "10.0.0.1", "cvss": 3.1}]},
        "instagram": {"available": True, "activity": {"dm": 3, "post": 1},
                      "caps": {"dm": 30, "post": 10},
                      "scheduled": [{"id": "ab12", "kind": "post",
                                     "when": 1_700_000_000.0, "media": ["a.jpg"]}]},
        "video": {"available": True, "activity": {"upload": 2},
                  "caps": {"upload": 10},
                  "scheduled": [{"id": "cd34", "platform": "youtube",
                                 "title": "My clip", "when": 1_700_000_000.0}]},
        "tasks": {"available": True, "total": 5, "active": 2, "max_concurrent": 3,
                  "queued": 1, "retries_total": 4, "by_status": {},
                  "items": [{"task_id": "t1", "goal": "research x",
                             "status": "running", "attempts": 1}]},
    }


# ── escaping / rendering ────────────────────────────────────────────────────

def test_esc():
    assert db._esc('<script>"x"&') == "&lt;script&gt;&quot;x&quot;&amp;"
    assert db._esc(None) == ""


def test_render_contains_sections(summary):
    html = db.render_html(summary)
    assert "JARVIS" in html and "Dashboard" in html
    assert "Security findings" in html and "Task queue" in html
    assert "Scheduled Instagram posts" in html
    assert "Scheduled video uploads" in html


def test_render_shows_data(summary):
    html = db.render_html(summary)
    assert "SQL injection" in html and "api.acme.com" in html
    assert "research x" in html and "My clip" in html
    assert "ab12" in html and "cd34" in html


def test_render_escapes_hostile_title(summary):
    summary["findings"]["items"][0]["title"] = "<script>alert(1)</script>"
    html = db.render_html(summary)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_empty_state():
    html = db.render_html({"health": {}, "findings": {}, "instagram": {},
                           "video": {}, "tasks": {}})
    assert "No findings logged yet" in html
    assert "No tasks in the queue" in html
    assert "Nothing scheduled" in html
    assert "No actions recorded today" in html


def test_render_pills(summary):
    html = db.render_html(summary)
    assert "API key set" in html and "daemon off" in html
    summary["health"]["api_key_configured"] = False
    summary["health"]["daemon_enabled"] = True
    html2 = db.render_html(summary)
    assert "API key missing" in html2 and "daemon on" in html2


def test_activity_bars(summary):
    html = db.render_html(summary)
    assert "3 / 30" in html and 'class="bar"' in html


def test_fmt_when():
    assert db._fmt_when(1_700_000_000.0) != "—"
    assert db._fmt_when("bad") == "—"


# ── collectors ──────────────────────────────────────────────────────────────

def test_collect_health_no_secrets(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": "fake-gemini-key-0123456789abcdef"}))
    h = db.collect_health(tmp_path)
    assert h["api_key_configured"] is True
    assert "fake-gemini-key" not in json.dumps(h)


def test_collect_health_placeholder_key(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": "YOUR_GEMINI_KEY_HERE"}))
    assert db.collect_health(tmp_path)["api_key_configured"] is False


def test_collect_health_missing_config(tmp_path):
    h = db.collect_health(tmp_path)
    assert h["api_key_configured"] is False
    assert h["directories"]["config"] is False


def test_collect_health_corrupt_config(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text("{bad")
    assert db.collect_health(tmp_path)["api_key_configured"] is False


def test_collect_tasks_does_not_start_queue(monkeypatch):
    from agent import task_queue as tq
    monkeypatch.setattr(tq, "_queue", None)
    started = []
    monkeypatch.setattr(tq, "get_queue", lambda: started.append(True))
    out = db.collect_tasks()
    assert started == []                 # read-only: never starts the queue
    assert out["total"] == 0 and out["available"] is True


def test_collect_tasks_reads_stats(monkeypatch):
    from agent import task_queue as tq
    q = tq.TaskQueue(max_concurrent=2)
    q.submit("a goal")
    monkeypatch.setattr(tq, "_queue", q)
    out = db.collect_tasks()
    assert out["total"] == 1 and out["max_concurrent"] == 2
    assert out["items"][0]["goal"] == "a goal"


def test_collect_instagram_shape(tmp_path, monkeypatch):
    from actions import instagram_manager as im
    monkeypatch.setattr(im, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(im, "QUEUE_PATH", tmp_path / "q.json")
    im.ActivityLedger().record("dm")        # real 'now' so counts_today() sees it
    out = db.collect_instagram()
    assert out["available"] and out["activity"]["dm"] == 1
    assert out["caps"]["dm"] == 30


def test_collect_video_shape(tmp_path, monkeypatch):
    from actions import video_manager as vm
    monkeypatch.setattr(vm, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(vm, "QUEUE_PATH", tmp_path / "q.json")
    out = db.collect_video()
    assert out["available"] and out["activity"] == {}


def test_collect_findings_shape():
    out = db.collect_findings()
    assert "items" in out and "summary" in out


def test_build_summary_keys(tmp_path):
    s = db.build_summary(tmp_path)
    assert set(s) == {"health", "findings", "instagram", "video", "tasks"}


def test_collector_survives_broken_module(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "actions" or "findings_agent" in name:
            raise ImportError("missing")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    out = db.collect_findings()
    assert out["available"] is False and "error" in out


# ── routing ────────────────────────────────────────────────────────────────

def test_route_root():
    status, ctype, body = db.route("/")
    assert status == 200 and "text/html" in ctype
    assert b"JARVIS" in body


def test_route_api_summary():
    status, ctype, body = db.route("/api/summary")
    assert status == 200 and ctype == "application/json"
    assert "health" in json.loads(body)


@pytest.mark.parametrize("path", ["/api/findings", "/api/instagram", "/api/video",
                                  "/api/tasks", "/api/health"])
def test_route_api_endpoints(path):
    status, ctype, body = db.route(path)
    assert status == 200 and ctype == "application/json"
    json.loads(body)


def test_route_query_string_stripped():
    assert db.route("/api/health?x=1")[0] == 200


def test_route_trailing_slash():
    assert db.route("/api/health/")[0] == 200


def test_route_healthz():
    status, ctype, body = db.route("/healthz")
    assert status == 200 and body == b"ok"


def test_route_404():
    status, _, body = db.route("/nope")
    assert status == 404 and json.loads(body)["error"] == "not found"


def test_route_no_traversal():
    assert db.route("/../../etc/passwd")[0] == 404


def test_route_handles_error(monkeypatch):
    monkeypatch.setattr(db, "build_summary", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    status, _, body = db.route("/api/summary")
    assert status == 500 and "boom" in json.loads(body)["error"]


# ── live server (loopback only) ─────────────────────────────────────────────

def test_live_server_endpoints():
    httpd = db.make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            assert r.status == 200
            assert b"JARVIS" in r.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/summary", timeout=10) as r:
            assert json.loads(r.read())["health"]["version"] == db.VERSION
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=10) as r:
            assert r.read() == b"ok"
        # POST must be rejected — the dashboard is read-only.
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/tasks", data=b"{}")
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "POST should have been rejected"
        except urllib.error.HTTPError as e:
            assert e.code == 405
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── tool entry point ────────────────────────────────────────────────────────

def test_control_start_stop(monkeypatch):
    monkeypatch.setattr(db, "_server", None)
    out = db.dashboard_control({"action": "start", "port": 0})
    assert "Dashboard running" in out
    try:
        assert "already running" in db.dashboard_control({"action": "start", "port": 0})
        assert "running on port" in db.dashboard_control({"action": "status"})
    finally:
        assert "stopped" in db.dashboard_control({"action": "stop"})


def test_control_status_when_off(monkeypatch):
    monkeypatch.setattr(db, "_server", None)
    assert "not running" in db.dashboard_control({"action": "status"})


def test_control_stop_when_off(monkeypatch):
    monkeypatch.setattr(db, "_server", None)
    assert "not running" in db.dashboard_control({"action": "stop"})


def test_control_unknown(monkeypatch):
    monkeypatch.setattr(db, "_server", None)
    assert "Unknown dashboard action" in db.dashboard_control({"action": "zzz"})


def test_main_json_flag(capsys):
    assert db.main(["--json"]) == 0
    assert "health" in json.loads(capsys.readouterr().out)
