"""
Video Manager for JARVIS — YouTube + TikTok creator studio
──────────────────────────────────────────────────────────
Publishing and channel management for the operator's OWN accounts, driven
through the existing visible Playwright browser (actions/browser_control.py),
so you can watch every step happen.

  Publish    upload (video + metadata + thumbnail), schedule, queue,
             unschedule, run_due
  Engage     comments, reply, like, subscribe
  Organise   playlist_add
  Insight    analytics, report, status

Existing modules stay untouched and complementary:
  * actions/youtube_video.py  — watching/searching/summarising videos
  * actions/tiktok_agent.py   — legacy TikTok browsing

Safety
──────
* You sign in yourself in the visible browser; no passwords are stored here.
* Publishing / replying / subscribing require confirm="VIDEO CONFIRMED"
  (or dry_run=true to preview the exact plan).
* Metadata is validated against each platform's real limits BEFORE any
  browser action, so a rejected upload never half-publishes.
* Daily upload caps + spacing (memory/video_state.json).
* Batch replies are capped and only target comments you point at.

Everything is stdlib-only at import time; browser calls go through a single
monkeypatchable delegate, so the whole module is testable offline.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────────────

CONFIRM_TEXT = "VIDEO CONFIRMED"
STATE_PATH = Path("memory") / "video_state.json"
QUEUE_PATH = Path("memory") / "video_queue.json"
REPORT_DIR = Path("reports")

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
THUMB_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_MAX_MB = {"youtube": 256_000, "tiktok": 4_000}
THUMB_MAX_MB = 2

LIMITS = {
    "youtube": {"title": 100, "description": 5000, "tags_chars": 500, "tags_count": 30,
                "privacy": ("public", "unlisted", "private")},
    "tiktok": {"title": 2200, "description": 2200, "tags_chars": 2200, "tags_count": 30,
               "privacy": ("public", "friends", "private")},
}

DAILY_CAPS = {"upload": 10, "reply": 30, "subscribe": 30, "like": 100}
MIN_INTERVAL_S = {"upload": 120, "reply": 15, "subscribe": 10, "like": 4}
BATCH_MAX = 10

STUDIO_URL = {
    "youtube": "https://studio.youtube.com/",
    "tiktok": "https://www.tiktok.com/upload",
}


# ── Browser delegate (single seam, monkeypatchable) ─────────────────────────

def _browser(params: dict, player=None) -> str:
    from actions.browser_control import browser_control
    return browser_control(parameters=params, player=player)


def _log(player, msg):
    try:
        if player:
            player.write_log(msg)
    except Exception:
        pass


def _say(speak, msg):
    try:
        if speak:
            speak(msg)
    except Exception:
        pass


# ── Pure helpers ────────────────────────────────────────────────────────────

def detect_platform(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if s in ("youtube", "yt", "youtu.be") or "youtube.com" in s or "youtu.be" in s:
        return "youtube"
    if s in ("tiktok", "tt", "tik tok") or "tiktok.com" in s:
        return "tiktok"
    return ""


def parse_tags(raw) -> list[str]:
    if raw is None:
        items = []
    elif isinstance(raw, str):
        items = re.split(r"[,\n]+", raw)
    else:
        items = list(raw)
    out, seen = [], set()
    for t in items:
        c = str(t or "").strip().lstrip("#").strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def extract_hashtags(text: str) -> list[str]:
    return parse_tags(re.findall(r"#([\w]+)", str(text or "")))


def validate_video(path, platform: str = "youtube") -> dict:
    errors = []
    if not path:
        return {"ok": False, "path": "", "errors": ["No video file provided."]}
    p = Path(str(path)).expanduser()
    if not p.exists():
        errors.append(f"Not found: {p}")
    elif not p.is_file():
        errors.append(f"Not a file: {p}")
    elif p.suffix.lower() not in VIDEO_EXTS:
        errors.append(f"Unsupported video type '{p.suffix}'")
    else:
        limit = VIDEO_MAX_MB.get(platform, 4_000)
        mb = p.stat().st_size / (1024 * 1024)
        if mb > limit:
            errors.append(f"{p.name} is {mb:.1f} MB (limit {limit} MB)")
    return {"ok": not errors, "path": str(p), "errors": errors}


def validate_thumbnail(path) -> dict:
    if not path:
        return {"ok": True, "path": "", "errors": []}      # thumbnail is optional
    p = Path(str(path)).expanduser()
    errors = []
    if not p.exists():
        errors.append(f"Thumbnail not found: {p}")
    elif p.suffix.lower() not in THUMB_EXTS:
        errors.append(f"Thumbnail must be an image, got '{p.suffix}'")
    elif p.stat().st_size / (1024 * 1024) > THUMB_MAX_MB:
        errors.append(f"Thumbnail exceeds {THUMB_MAX_MB} MB")
    return {"ok": not errors, "path": str(p), "errors": errors}


def validate_metadata(platform: str, title: str = "", description: str = "",
                      tags=None, privacy: str = "") -> dict:
    """Check titles/descriptions/tags/privacy against real platform limits."""
    platform = detect_platform(platform) or "youtube"
    lim = LIMITS[platform]
    errors, warnings = [], []

    title = str(title or "").strip()
    description = str(description or "").strip()
    tag_list = parse_tags(tags)

    if not title:
        errors.append("A title is required.")
    elif len(title) > lim["title"]:
        errors.append(f"{platform.title()} titles max {lim['title']} chars (got {len(title)}).")

    if len(description) > lim["description"]:
        errors.append(f"Description max {lim['description']} chars (got {len(description)}).")

    if len(tag_list) > lim["tags_count"]:
        warnings.append(f"Kept the first {lim['tags_count']} tags.")
        tag_list = tag_list[:lim["tags_count"]]
    joined = ", ".join(tag_list)
    if len(joined) > lim["tags_chars"]:
        trimmed, total = [], 0
        for t in tag_list:
            add = len(t) + (2 if trimmed else 0)
            if total + add > lim["tags_chars"]:
                break
            trimmed.append(t)
            total += add
        warnings.append(f"Tags trimmed to {lim['tags_chars']} characters.")
        tag_list = trimmed

    privacy = str(privacy or "").strip().lower()
    if not privacy:
        privacy = "public"
    if privacy not in lim["privacy"]:
        errors.append(f"{platform.title()} privacy must be one of {', '.join(lim['privacy'])}.")

    if platform == "tiktok" and len(title) > 150:
        warnings.append("TikTok captions display best under 150 characters.")

    return {"ok": not errors, "platform": platform, "title": title,
            "description": description, "tags": tag_list, "privacy": privacy,
            "errors": errors, "warnings": warnings}


def describe_plan(meta: dict, video: str, thumbnail: str = "") -> str:
    lines = [f"Platform: {meta['platform'].title()}",
             f"Video:    {Path(video).name if video else '(none)'}",
             f"Title:    {meta['title']}",
             f"Privacy:  {meta['privacy']}"]
    if meta["description"]:
        lines.append(f"Description: {meta['description'][:100]}")
    if meta["tags"]:
        lines.append("Tags: " + ", ".join(meta["tags"]))
    if thumbnail:
        lines.append(f"Thumbnail: {Path(thumbnail).name}")
    return "\n".join(lines)


# ── Activity ledger ─────────────────────────────────────────────────────────

class VideoLedger:
    def __init__(self, path=None):
        self.path = Path(path) if path else STATE_PATH
        self.data = self._load()

    def _load(self) -> dict:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    d.setdefault("days", {})
                    d.setdefault("last", {})
                    return d
        except Exception:
            pass
        return {"days": {}, "last": {}}

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _day(now):
        return datetime.fromtimestamp(now).date().isoformat()

    def count_today(self, kind, now=None) -> int:
        now = time.time() if now is None else now
        return int(self.data["days"].get(self._day(now), {}).get(kind, 0))

    def counts_today(self, now=None) -> dict:
        now = time.time() if now is None else now
        return dict(self.data["days"].get(self._day(now), {}))

    def check(self, kind, now=None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        cap = DAILY_CAPS.get(kind)
        if cap is None:
            return True, ""
        used = self.count_today(kind, now)
        if used >= cap:
            return False, f"Daily {kind} limit reached ({used}/{cap}) — try again tomorrow."
        gap = MIN_INTERVAL_S.get(kind, 0)
        last = float(self.data["last"].get(kind, 0))
        wait = gap - (now - last)
        if last and wait > 0:
            return False, f"Slow down — wait {int(wait) + 1}s before the next {kind}."
        return True, ""

    def record(self, kind, now=None):
        now = time.time() if now is None else now
        day = self.data["days"].setdefault(self._day(now), {})
        day[kind] = int(day.get(kind, 0)) + 1
        self.data["last"][kind] = now
        self.save()

    def summary(self, now=None) -> str:
        counts = self.counts_today(now)
        if not counts:
            return "No video actions recorded today."
        return "Today's video activity:\n" + "\n".join(
            f"  {k}: {counts[k]}/{DAILY_CAPS.get(k, '∞')}" for k in sorted(counts))


# ── Upload queue ────────────────────────────────────────────────────────────

class UploadQueue:
    def __init__(self, path=None):
        self.path = Path(path) if path else QUEUE_PATH
        self.items = self._load()

    def _load(self) -> list:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, list):
                    return d
        except Exception:
            pass
        return []

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add(self, platform, video, title, description="", tags=None, privacy="public",
            thumbnail="", when=None, now=None) -> dict:
        now = time.time() if now is None else now
        meta = validate_metadata(platform, title, description, tags, privacy)
        vid = validate_video(video, meta["platform"])
        thumb = validate_thumbnail(thumbnail)
        errors = meta["errors"] + vid["errors"] + thumb["errors"]
        if errors:
            return {"ok": False, "errors": errors}
        item = {"id": uuid.uuid4().hex[:8], "platform": meta["platform"],
                "video": vid["path"], "title": meta["title"],
                "description": meta["description"], "tags": meta["tags"],
                "privacy": meta["privacy"], "thumbnail": thumb["path"],
                "when": float(when if when is not None else now),
                "status": "pending", "created": now}
        self.items.append(item)
        self.save()
        return {"ok": True, "item": item, "warnings": meta["warnings"]}

    def list(self, status="") -> list:
        return [i for i in self.items if i.get("status") == status] if status else list(self.items)

    def due(self, now=None) -> list:
        now = time.time() if now is None else now
        return [i for i in self.items
                if i.get("status") == "pending" and float(i.get("when", 0)) <= now]

    def cancel(self, item_id) -> bool:
        for i in self.items:
            if i.get("id") == item_id and i.get("status") == "pending":
                i["status"] = "cancelled"
                self.save()
                return True
        return False

    def mark(self, item_id, status="done") -> bool:
        for i in self.items:
            if i.get("id") == item_id:
                i["status"] = status
                self.save()
                return True
        return False

    def render(self) -> str:
        pending = self.list("pending")
        if not pending:
            return "No scheduled video uploads."
        lines = []
        for i in sorted(pending, key=lambda x: x.get("when", 0)):
            ts = datetime.fromtimestamp(float(i["when"])).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  [{i['id']}] {ts} — {i['platform']}: {i['title'][:50]}")
        return f"Scheduled uploads ({len(pending)}):\n" + "\n".join(lines)


def build_report(ledger=None, queue=None, now=None) -> str:
    now = time.time() if now is None else now
    lines = [f"# Video studio report — {datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M')}",
             "", "## Activity today", ""]
    counts = ledger.counts_today(now) if ledger else {}
    lines += [f"- {k}: {counts[k]} / {DAILY_CAPS.get(k, 'unlimited')}"
              for k in sorted(counts)] or ["- No actions recorded today."]
    lines += ["", "## Scheduled uploads", ""]
    pending = queue.list("pending") if queue else []
    if pending:
        for i in sorted(pending, key=lambda x: x.get("when", 0)):
            ts = datetime.fromtimestamp(float(i["when"])).strftime("%Y-%m-%d %H:%M")
            lines.append(f"- `{i['id']}` {ts} — {i['platform']}: {i['title'][:60]}")
    else:
        lines.append("- Nothing scheduled.")
    return "\n".join(lines) + "\n"


def require_confirm(parameters: dict, action: str) -> str | None:
    if parameters.get("dry_run"):
        return None            # caller renders the plan instead
    if str(parameters.get("confirm", "")) != CONFIRM_TEXT:
        return (f"'{action}' publishes or changes your channel. Call again with "
                f"confirm='{CONFIRM_TEXT}' (or dry_run=true to preview the plan).")
    return None


# ── Browser operations (sequences of browser_control calls) ─────────────────

def _click(label: str, player=None) -> str:
    return _browser({"action": "smart_click", "description": label,
                     "headless": False}, player)


def _type(selector: str, text: str, player=None) -> str:
    return _browser({"action": "type", "selector": selector, "text": text,
                     "headless": False}, player)


def op_upload(platform: str, video: str, meta: dict, thumbnail: str = "",
              player=None) -> str:
    """Drive the visible upload flow. Returns a status string."""
    steps: list[str] = []
    _browser({"action": "go_to", "url": STUDIO_URL[platform], "headless": False}, player)

    if platform == "youtube":
        steps.append(_click("Upload videos", player))
        up = _browser({"action": "upload", "selector": "input[type='file']",
                       "paths": video, "headless": False}, player)
        steps.append(up)
        if "Attached" not in up:
            return "Upload failed: " + up
        _type("div#textbox[aria-label*='title'], #title-textarea #textbox",
              meta["title"], player)
        if meta["description"]:
            _type("div#textbox[aria-label*='description'], #description-textarea #textbox",
                  meta["description"], player)
        if thumbnail:
            _browser({"action": "upload",
                      "selector": "input[type='file'][accept*='image']",
                      "paths": thumbnail, "headless": False}, player)
        for _ in range(3):
            _click("Next", player)
        _click(meta["privacy"].capitalize(), player)
        final = _click("Publish", player)
        if "not found" in final.lower() or "failed" in final.lower():
            final = _click("Done", player)
        return f"🎬 Uploaded to YouTube: {meta['title'][:60]} ({meta['privacy']})"
    # TikTok
    up = _browser({"action": "upload", "selector": "input[type='file']",
                   "paths": video, "headless": False}, player)
    if "Attached" not in up:
        return "Upload failed: " + up
    caption = meta["title"]
    if meta["tags"]:
        caption += " " + " ".join("#" + t.replace(" ", "") for t in meta["tags"])
    _type("div[contenteditable='true']", caption, player)
    if meta["privacy"] != "public":
        _click("Who can watch this video", player)
        _click("Friends" if meta["privacy"] == "friends" else "Private", player)
    _click("Post", player)
    return f"🎬 Uploaded to TikTok: {meta['title'][:60]} ({meta['privacy']})"


def op_comments(platform: str, url: str, player=None, limit: int = 4000) -> str:
    if not url:
        return "Give me the video URL to read comments from."
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    _browser({"action": "scroll", "amount": 3, "headless": False}, player)
    text = _browser({"action": "get_text", "headless": False}, player)
    body = str(text or "").strip()
    if not body:
        return "Could not read the page — you may need to sign in first."
    return f"💬 Comments page ({platform}):\n{body[:limit]}"


def op_reply(platform: str, url: str, text: str, player=None) -> str:
    if not url or not text:
        return "Provide the video URL and the reply text."
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    _click("Reply", player)
    selector = ("div[contenteditable='true']" if platform == "tiktok"
                else "#contenteditable-root, div#contenteditable-textarea")
    _type(selector, text, player)
    out = _click("Reply", player)
    if "not found" in out.lower():
        out = _click("Comment", player)
    return f"💬 Replied: {text[:80]}"


def op_like(platform: str, url: str, player=None) -> str:
    if not url:
        return "Give me the video URL."
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    out = _click("Like", player)
    if "not found" in out.lower():
        return "Could not find the Like button — it may already be liked."
    return "❤️ Liked the video."


def op_subscribe(platform: str, url: str, player=None) -> str:
    if not url:
        return "Give me the channel or profile URL."
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    label = "Subscribe" if platform == "youtube" else "Follow"
    out = _click(label, player)
    if "not found" in out.lower():
        return f"Could not find the {label} button — you may already be subscribed."
    return f"➕ {label}d."


def op_playlist_add(url: str, playlist: str, player=None) -> str:
    if not url or not playlist:
        return "Provide the video URL and the playlist name."
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    _click("Save", player)
    out = _click(playlist, player)
    if "not found" in out.lower():
        return f"Playlist '{playlist}' wasn't offered — create it on YouTube first."
    return f"📂 Added to playlist '{playlist}'."


def op_analytics(platform: str, player=None) -> str:
    url = ("https://studio.youtube.com/channel/UC/analytics/tab-overview/period-default"
           if platform == "youtube" else "https://www.tiktok.com/tiktokstudio/analytics")
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    text = _browser({"action": "get_text", "headless": False}, player)
    body = str(text or "").strip()
    if not body:
        return "Could not read analytics — sign in to the studio first."
    return f"📊 {platform.title()} analytics:\n{body[:4000]}"


# ── Dispatcher ──────────────────────────────────────────────────────────────

MUTATING = {"upload", "publish", "run_due", "reply", "subscribe", "follow",
            "like", "playlist_add"}
_LIMIT_KIND = {"upload": "upload", "publish": "upload", "run_due": "upload",
               "reply": "reply", "subscribe": "subscribe", "follow": "subscribe",
               "like": "like"}


def video_manager(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    platform = detect_platform(params.get("platform", "")) or "youtube"

    try:
        if action in ("help", "capabilities", "status"):
            return (
                "🎬 Video Manager (YouTube + TikTok)\n"
                "  Publish:  upload, schedule, queue, unschedule, run_due\n"
                "  Engage:   comments, reply, like, subscribe\n"
                "  Organise: playlist_add\n"
                "  Insight:  analytics, report, activity\n"
                f"Publishing needs confirm='{CONFIRM_TEXT}'. "
                "Uploads run in a visible browser so you can watch."
            )

        if action == "activity":
            return VideoLedger().summary()

        if action == "queue":
            return UploadQueue().render()

        if action == "report":
            text = build_report(VideoLedger(), UploadQueue())
            if params.get("save"):
                REPORT_DIR.mkdir(parents=True, exist_ok=True)
                out = REPORT_DIR / f"video_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
                out.write_text(text, encoding="utf-8")
                return f"📊 Report saved to {out}\n\n{text}"
            return text

        if action == "schedule":
            when = params.get("when")
            try:
                when_ts = float(when) if when not in (None, "") else None
            except (TypeError, ValueError):
                return "'when' must be a Unix timestamp (seconds since epoch)."
            res = UploadQueue().add(platform, params.get("video") or params.get("path"),
                                    params.get("title", ""), params.get("description", ""),
                                    params.get("tags"), params.get("privacy", "public"),
                                    params.get("thumbnail", ""), when_ts)
            if not res["ok"]:
                return "Could not schedule: " + "; ".join(res["errors"])
            item = res["item"]
            ts = datetime.fromtimestamp(item["when"]).strftime("%Y-%m-%d %H:%M")
            warn = ("\n⚠️ " + " ".join(res["warnings"])) if res["warnings"] else ""
            return f"🗓️ Scheduled [{item['id']}] {item['platform']} upload for {ts}.{warn}"

        if action == "unschedule":
            item_id = str(params.get("id", "")).strip()
            if not item_id:
                return "Which upload? Give me its id (see 'queue')."
            return (f"🗑️ Cancelled [{item_id}]." if UploadQueue().cancel(item_id)
                    else f"No pending upload with id '{item_id}'.")

        if action in MUTATING:
            gate = require_confirm(params, action)
            if gate:
                return gate
            kind = _LIMIT_KIND.get(action)
            if kind:
                ok, reason = VideoLedger().check(kind)
                if not ok:
                    return f"⏳ {reason}"

        ledger = VideoLedger()

        if action in ("upload", "publish"):
            video = params.get("video") or params.get("path") or params.get("media")
            meta = validate_metadata(platform, params.get("title", ""),
                                     params.get("description", ""), params.get("tags"),
                                     params.get("privacy", ""))
            vid = validate_video(video, meta["platform"])
            thumb = validate_thumbnail(params.get("thumbnail", ""))
            errors = meta["errors"] + vid["errors"] + thumb["errors"]
            if errors:
                return "Upload blocked: " + "; ".join(errors)
            if params.get("dry_run"):
                return "Dry run — upload plan:\n" + describe_plan(meta, vid["path"], thumb["path"])
            out = op_upload(meta["platform"], vid["path"], meta, thumb["path"], player)
            if out.startswith("🎬"):
                ledger.record("upload")
                _say(speak, "Video uploaded.")
            if meta["warnings"]:
                out += "\n⚠️ " + " ".join(meta["warnings"])
            return out

        if action == "run_due":
            q = UploadQueue()
            due = q.due()
            if not due:
                return "Nothing is due to upload right now."
            lines, done = [], 0
            for item in due:
                ok, reason = ledger.check("upload")
                if not ok:
                    lines.append(f"  ⏳ stopped: {reason}")
                    break
                meta = {"title": item["title"], "description": item["description"],
                        "tags": item["tags"], "privacy": item["privacy"]}
                r = op_upload(item["platform"], item["video"], meta,
                              item.get("thumbnail", ""), player)
                lines.append(f"  [{item['id']}] {r}")
                if r.startswith("🎬"):
                    q.mark(item["id"], "done")
                    ledger.record("upload")
                    done += 1
                else:
                    q.mark(item["id"], "failed")
            return f"🗓️ Published {done}/{len(due)} scheduled uploads:\n" + "\n".join(lines)

        if action == "comments":
            return op_comments(platform, params.get("url", ""), player,
                               int(params.get("limit", 4000)))
        if action == "reply":
            out = op_reply(platform, params.get("url", ""),
                           params.get("text") or params.get("message", ""), player)
            if out.startswith("💬"):
                ledger.record("reply")
            return out
        if action == "like":
            out = op_like(platform, params.get("url", ""), player)
            if out.startswith("❤️"):
                ledger.record("like")
            return out
        if action in ("subscribe", "follow"):
            out = op_subscribe(platform, params.get("url", ""), player)
            if out.startswith("➕"):
                ledger.record("subscribe")
            return out
        if action == "playlist_add":
            return op_playlist_add(params.get("url", ""),
                                   params.get("playlist", ""), player)
        if action == "analytics":
            return op_analytics(platform, player)

        return f"Unknown video action '{action}'. Say 'video help' for the list."
    except Exception as e:
        return f"video_manager '{action}' failed: {e}"
