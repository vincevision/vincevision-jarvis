"""
JARVIS local dashboard
──────────────────────
A read-only web dashboard for everything JARVIS is doing: pentest findings,
Instagram activity + schedule, video uploads, the parallel task queue, and a
health check.

Stdlib only (http.server) — no Flask, no build step, no external assets.

    python -m core.dashboard --port 8765

Design notes:
  * READ-ONLY. There are no mutating endpoints, so opening it can't change
    your accounts or delete anything.
  * Never exposes secrets: API keys are reported as present/absent booleans.
  * Every data source is optional and wrapped — a missing module or database
    degrades to an empty section instead of a 500.
  * `build_summary()` and `render_html()` are pure, so the whole UI is
    testable without starting a server.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
VERSION = "1.0"


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


# ── Data collectors (each one optional) ─────────────────────────────────────

def collect_findings(limit: int = 50) -> dict:
    out = {"available": False, "summary": {}, "items": []}
    try:
        from actions import findings_agent as fa
        out["summary"] = fa.summary()
        rows = fa.list_findings(limit=limit)
        out["items"] = [
            {"id": r.get("id"), "title": r.get("title", ""),
             "severity": r.get("severity", ""), "status": r.get("status", ""),
             "target": r.get("target", ""), "cvss": r.get("cvss", "")}
            for r in rows
        ]
        out["available"] = True
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def collect_instagram() -> dict:
    out = {"available": False, "activity": {}, "scheduled": []}
    try:
        from actions import instagram_manager as im
        out["activity"] = im.ActivityLedger().counts_today()
        out["caps"] = dict(im.DAILY_CAPS)
        for i in im.PostQueue().list("pending"):
            out["scheduled"].append({
                "id": i.get("id"), "kind": i.get("kind"),
                "when": float(i.get("when", 0)),
                "media": [Path(m).name for m in i.get("media", [])],
            })
        out["available"] = True
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def collect_video() -> dict:
    out = {"available": False, "activity": {}, "scheduled": []}
    try:
        from actions import video_manager as vm
        out["activity"] = vm.VideoLedger().counts_today()
        out["caps"] = dict(vm.DAILY_CAPS)
        for i in vm.UploadQueue().list("pending"):
            out["scheduled"].append({
                "id": i.get("id"), "platform": i.get("platform"),
                "title": i.get("title", ""), "when": float(i.get("when", 0)),
            })
        out["available"] = True
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def collect_tasks() -> dict:
    """Read queue stats WITHOUT starting the queue (dashboard is read-only)."""
    out = {"available": False, "total": 0, "active": 0, "max_concurrent": 0,
           "queued": 0, "retries_total": 0, "by_status": {}, "items": []}
    try:
        from agent import task_queue as tq
        out["max_concurrent"] = tq.default_concurrency()
        q = getattr(tq, "_queue", None)
        if q is not None:
            out.update(q.get_stats())
            out["items"] = q.get_all_statuses()[:25]
        out["available"] = True
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def collect_health(base_dir: Path | None = None) -> dict:
    base = Path(base_dir) if base_dir else _base_dir()
    cfg = base / "config"
    keys_present = False
    try:
        kf = cfg / "api_keys.json"
        if kf.exists():
            data = json.loads(kf.read_text(encoding="utf-8"))
            key = str(data.get("gemini_api_key", "") or "")
            keys_present = len(key) >= 20 and "YOUR_" not in key.upper()
    except Exception:
        pass

    daemon_on = False
    try:
        from core.daemon import daemon_enabled_by_default
        daemon_on = daemon_enabled_by_default()
    except Exception:
        pass

    dirs = {}
    for name in ("config", "memory", "logs", "reports", "browser_profiles"):
        try:
            dirs[name] = (base / name).exists()
        except OSError:
            dirs[name] = False

    return {
        "python": sys.version.split()[0],
        "version": VERSION,
        "api_key_configured": keys_present,      # boolean only — never the key
        "daemon_enabled": daemon_on,
        "directories": dirs,
        "generated": datetime.now().isoformat(timespec="seconds"),
    }


def build_summary(base_dir: Path | None = None) -> dict:
    return {
        "health": collect_health(base_dir),
        "findings": collect_findings(),
        "instagram": collect_instagram(),
        "video": collect_video(),
        "tasks": collect_tasks(),
    }


# ── Rendering ───────────────────────────────────────────────────────────────

_CSS = """
:root{--bg:#0b0f17;--card:#141a26;--line:#232c3d;--txt:#e6edf7;--dim:#8b9ab3;
--acc:#4da3ff;--ok:#3ddc97;--warn:#ffb454;--bad:#ff5c7c;--crit:#c86bff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
header{padding:22px 28px;border-bottom:1px solid var(--line);
background:linear-gradient(90deg,#111827,#0b0f17);display:flex;
align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
h1{margin:0;font-size:19px;letter-spacing:.4px}
h1 span{color:var(--acc)}
.sub{color:var(--dim);font-size:12px}
main{padding:24px 28px;max-width:1240px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h2{margin:0 0 10px;font-size:12px;text-transform:uppercase;
letter-spacing:.9px;color:var(--dim);font-weight:600}
.big{font-size:30px;font-weight:650;line-height:1.1}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;
border:1px solid var(--line);color:var(--dim)}
.pill.ok{color:var(--ok);border-color:#1d4d3c}
.pill.bad{color:var(--bad);border-color:#5c2233}
.pill.warn{color:var(--warn);border-color:#5c4420}
section{margin-top:22px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.6px}
tr:last-child td{border-bottom:none}
.sev{font-weight:600;text-transform:capitalize}
.sev.critical{color:var(--crit)}.sev.high{color:var(--bad)}
.sev.medium{color:var(--warn)}.sev.low{color:var(--acc)}.sev.info{color:var(--dim)}
.empty{color:var(--dim);padding:14px 0;font-style:italic}
.bar{height:6px;background:#1d2637;border-radius:4px;overflow:hidden;margin-top:7px}
.bar i{display:block;height:100%;background:var(--acc)}
footer{color:var(--dim);font-size:11px;padding:18px 28px;text-align:center}
a{color:var(--acc)}
"""

_JS = """
async function refresh(){
  try{
    const r = await fetch('/api/summary');
    if(!r.ok) return;
    const d = await r.json();
    document.getElementById('stamp').textContent = d.health.generated;
    const set=(id,v)=>{const e=document.getElementById(id); if(e) e.textContent=v;};
    set('f-total', d.findings.summary.total ?? 0);
    set('t-active', d.tasks.active ?? 0);
    set('t-total', d.tasks.total ?? 0);
    set('ig-count', Object.values(d.instagram.activity||{}).reduce((a,b)=>a+b,0));
    set('vid-count', Object.values(d.video.activity||{}).reduce((a,b)=>a+b,0));
  }catch(e){}
}
setInterval(refresh, 10000); refresh();
"""


def _esc(text) -> str:
    s = str(text if text is not None else "")
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _fmt_when(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _activity_rows(activity: dict, caps: dict) -> str:
    if not activity:
        return '<div class="empty">No actions recorded today.</div>'
    rows = []
    for kind in sorted(activity):
        used = activity[kind]
        cap = caps.get(kind)
        pct = min(100, int(used / cap * 100)) if cap else 0
        label = f"{used} / {cap}" if cap else f"{used}"
        rows.append(
            f"<tr><td>{_esc(kind)}</td><td>{_esc(label)}"
            f'<div class="bar"><i style="width:{pct}%"></i></div></td></tr>')
    return "<table><tr><th>Action</th><th>Today</th></tr>" + "".join(rows) + "</table>"


def render_html(summary: dict) -> str:
    health = summary.get("health", {})
    findings = summary.get("findings", {})
    ig = summary.get("instagram", {})
    vid = summary.get("video", {})
    tasks = summary.get("tasks", {})
    fsum = findings.get("summary", {}) or {}

    key_pill = ('<span class="pill ok">API key set</span>' if health.get("api_key_configured")
                else '<span class="pill bad">API key missing</span>')
    daemon_pill = ('<span class="pill warn">daemon on</span>' if health.get("daemon_enabled")
                   else '<span class="pill ok">daemon off</span>')

    cards = [
        ("Findings", f'<div class="big" id="f-total">{fsum.get("total", 0)}</div>'
                     f'<div class="sub">security findings logged</div>'),
        ("Tasks running", f'<div class="big" id="t-active">{tasks.get("active", 0)}</div>'
                          f'<div class="sub">of {tasks.get("max_concurrent", 0)} parallel slots</div>'),
        ("Tasks total", f'<div class="big" id="t-total">{tasks.get("total", 0)}</div>'
                        f'<div class="sub">{tasks.get("retries_total", 0)} auto-retries</div>'),
        ("Instagram", f'<div class="big" id="ig-count">'
                      f'{sum((ig.get("activity") or {}).values())}</div>'
                      f'<div class="sub">{len(ig.get("scheduled") or [])} scheduled</div>'),
        ("Video", f'<div class="big" id="vid-count">'
                  f'{sum((vid.get("activity") or {}).values())}</div>'
                  f'<div class="sub">{len(vid.get("scheduled") or [])} scheduled</div>'),
    ]
    card_html = "".join(
        f'<div class="card"><h2>{_esc(t)}</h2>{body}</div>' for t, body in cards)

    # Findings table
    items = findings.get("items") or []
    if items:
        rows = "".join(
            f'<tr><td>{_esc(i.get("id"))}</td><td>{_esc(i.get("title"))}</td>'
            f'<td class="sev {_esc(i.get("severity"))}">{_esc(i.get("severity"))}</td>'
            f'<td>{_esc(i.get("target"))}</td><td>{_esc(i.get("status"))}</td></tr>'
            for i in items)
        findings_html = ("<table><tr><th>#</th><th>Title</th><th>Severity</th>"
                         "<th>Target</th><th>Status</th></tr>" + rows + "</table>")
    else:
        findings_html = '<div class="empty">No findings logged yet.</div>'

    # Tasks table
    titems = tasks.get("items") or []
    if titems:
        rows = "".join(
            f'<tr><td>{_esc(t.get("task_id"))}</td><td>{_esc(t.get("goal"))}</td>'
            f'<td>{_esc(t.get("status"))}</td><td>{_esc(t.get("attempts", 0))}</td></tr>'
            for t in titems)
        tasks_html = ("<table><tr><th>ID</th><th>Goal</th><th>Status</th>"
                      "<th>Attempts</th></tr>" + rows + "</table>")
    else:
        tasks_html = '<div class="empty">No tasks in the queue.</div>'

    def schedule_table(rows_data, cols):
        if not rows_data:
            return '<div class="empty">Nothing scheduled.</div>'
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in r) + "</tr>"
                       for r in rows_data)
        return f"<table><tr>{head}</tr>{body}</table>"

    ig_rows = [[i.get("id"), i.get("kind"), ", ".join(i.get("media") or []),
                _fmt_when(i.get("when"))] for i in (ig.get("scheduled") or [])]
    vid_rows = [[i.get("id"), i.get("platform"), i.get("title"), _fmt_when(i.get("when"))]
                for i in (vid.get("scheduled") or [])]

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Dashboard</title><style>{_CSS}</style></head>
<body>
<header>
  <div><h1>JARVIS <span>Dashboard</span></h1>
  <div class="sub">Read-only overview · updated <span id="stamp">{_esc(health.get('generated', ''))}</span></div></div>
  <div>{key_pill} {daemon_pill} <span class="pill">Python {_esc(health.get('python', ''))}</span></div>
</header>
<main>
  <div class="grid">{card_html}</div>

  <section class="card"><h2>Security findings</h2>{findings_html}</section>

  <section class="card"><h2>Task queue</h2>{tasks_html}</section>

  <div class="grid" style="margin-top:22px">
    <div class="card"><h2>Instagram activity</h2>
      {_activity_rows(ig.get('activity') or {}, ig.get('caps') or {})}</div>
    <div class="card"><h2>Video activity</h2>
      {_activity_rows(vid.get('activity') or {}, vid.get('caps') or {})}</div>
  </div>

  <section class="card"><h2>Scheduled Instagram posts</h2>
    {schedule_table(ig_rows, ['ID', 'Kind', 'Media', 'When'])}</section>

  <section class="card"><h2>Scheduled video uploads</h2>
    {schedule_table(vid_rows, ['ID', 'Platform', 'Title', 'When'])}</section>
</main>
<footer>JARVIS dashboard v{_esc(VERSION)} · read-only · no secrets are displayed</footer>
<script>{_JS}</script>
</body></html>"""


# ── Routing (pure, testable) ────────────────────────────────────────────────

def route(path: str, base_dir: Path | None = None) -> tuple[int, str, bytes]:
    """Return (status, content_type, body) for a request path."""
    clean = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    try:
        if clean == "/":
            return 200, "text/html; charset=utf-8", render_html(build_summary(base_dir)).encode("utf-8")
        if clean == "/api/summary":
            data = build_summary(base_dir)
        elif clean == "/api/findings":
            data = collect_findings()
        elif clean == "/api/instagram":
            data = collect_instagram()
        elif clean == "/api/video":
            data = collect_video()
        elif clean == "/api/tasks":
            data = collect_tasks()
        elif clean == "/api/health":
            data = collect_health(base_dir)
        elif clean == "/healthz":
            return 200, "text/plain; charset=utf-8", b"ok"
        else:
            return 404, "application/json", json.dumps({"error": "not found"}).encode("utf-8")
        return 200, "application/json", json.dumps(data, default=str).encode("utf-8")
    except Exception as e:
        return 500, "application/json", json.dumps({"error": str(e)[:200]}).encode("utf-8")


# ── Server ──────────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    server_version = f"JarvisDashboard/{VERSION}"
    base_dir = None

    def do_GET(self):
        status, ctype, body = route(self.path, self.base_dir)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        body = json.dumps({"error": "dashboard is read-only"}).encode("utf-8")
        self.send_response(405)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass          # keep the console quiet


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                base_dir: Path | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"base_dir": base_dir})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def dashboard_control(parameters: dict, player=None, speak=None) -> str:
    """Voice/tool entry point: start the dashboard in a background thread."""
    global _server, _thread
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    port = int(params.get("port", DEFAULT_PORT))
    if action in ("start", "open"):
        if _server is not None:
            return f"📊 Dashboard already running on port {_server.server_address[1]}."
        try:
            _server = make_server(DEFAULT_HOST, port)
        except OSError as e:
            return f"Could not start dashboard on port {port}: {e}"
        _thread = threading.Thread(target=_server.serve_forever, daemon=True,
                                   name="JarvisDashboard")
        _thread.start()
        return f"📊 Dashboard running at http://localhost:{port}"
    if action == "stop":
        if _server is None:
            return "Dashboard is not running."
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass
        _server = None
        return "📊 Dashboard stopped."
    if action == "status":
        if _server is None:
            return "Dashboard is not running. Say 'start dashboard'."
        return f"📊 Dashboard running on port {_server.server_address[1]}."
    return f"Unknown dashboard action '{action}'. Try start, stop, status."


_server = None
_thread = None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="JARVIS local dashboard (read-only)")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--json", action="store_true", help="print the summary JSON and exit")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(build_summary(), indent=2, default=str))
        return 0

    try:
        httpd = make_server(args.host, args.port)
    except OSError as e:
        print(f"Could not bind {args.host}:{args.port} — {e}")
        return 1
    print(f"📊 JARVIS dashboard on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
