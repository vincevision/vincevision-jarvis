"""
Instagram Manager for JARVIS — full account management
───────────────────────────────────────────────────────
A much richer layer on top of actions/instagram_agent.py. It reuses that
agent's browser session (you sign in yourself; JARVIS never sees your
password) and adds real management features:

  Messaging   inbox, dm_read, dm (text), dm_image (photo), dm_many (bounded)
  Publishing  post (photo), carousel (2-10 files), reel (video), story,
              schedule / queue / unschedule / run_due
  Following   follow, unfollow, follow_many (bounded), followers, following,
              not_following_back, mutuals, requests (accept/decline)
  Engagement  like, unlike, comment, save, comments
  Profile     profile (stats), edit_bio, set_avatar, my_posts
  Insight     activity (rate-limit ledger), report (markdown)

Safety model
────────────
* Your password is never read, typed, or stored — login is manual in a real
  browser window; only the session profile is persisted (gitignored).
* No CAPTCHA / 2FA bypass.
* Every account-changing or publishing action needs
  confirm="INSTAGRAM CONFIRMED" (or dry_run=True to preview).
* Daily caps + minimum spacing between actions (memory/instagram_state.json)
  keep usage human-paced and protect the account from action blocks.
* Batch actions only accept usernames YOU supply, hard-capped per call.
  There is no scrape-then-spam loop: follower lists are for analysis only.

All browser access is lazy; this module imports only the standard library at
import time, and every browser operation accepts an injected driver so it can
be tested offline.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

# ── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "https://www.instagram.com"
CONFIRM_TEXT = "INSTAGRAM CONFIRMED"          # matches instagram_agent

CAPTION_MAX = 2200
HASHTAG_MAX = 30
CAROUSEL_MAX = 10
BATCH_MAX = 10                                 # explicit usernames per call
LIST_SCROLL_MAX = 20
LIST_RESULT_MAX = 500

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
IMAGE_MAX_MB = 30
VIDEO_MAX_MB = 650

STATE_PATH = Path("memory") / "instagram_state.json"
QUEUE_PATH = Path("memory") / "instagram_queue.json"
REPORT_DIR = Path("reports")

# Human-paced limits. Conservative on purpose.
DAILY_CAPS = {
    "follow": 40, "unfollow": 40, "dm": 30,
    "comment": 30, "like": 100, "post": 10, "story": 10,
}
MIN_INTERVAL_S = {
    "follow": 20, "unfollow": 20, "dm": 15,
    "comment": 20, "like": 5, "post": 120, "story": 60,
}

# WebDriver locator strategies / key codes as plain strings, so browser
# operations never need to import selenium (keeps offline tests dependency-free).
CSS = "css selector"
XPATH = "xpath"
ENTER = "\ue007"

_USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")


# ── Lazy delegates to the existing agent ────────────────────────────────────

def _ig():
    from actions import instagram_agent
    return instagram_agent


def _log(player, msg: str):
    try:
        if player:
            player.write_log(msg)
    except Exception:
        pass


def _say(speak, msg: str):
    try:
        if speak:
            speak(msg)
    except Exception:
        pass


def _session(parameters: dict, player=None):
    """Return (driver, error_message). Reuses instagram_agent's saved session."""
    ig = _ig()
    try:
        driver = ig._make_driver(parameters, player=player)
    except Exception as e:
        return None, f"Could not start the Instagram browser: {e}"
    try:
        msg = ig._ensure_logged_in(driver, parameters, player=player)
    except Exception as e:
        return driver, f"Login check failed: {e}"
    if msg:
        return driver, msg
    return driver, None


# ── Pure helpers: usernames ─────────────────────────────────────────────────

def normalize_username(raw: str) -> str:
    """'@Some.User ' -> 'some.user'. Returns '' if not a valid IG handle."""
    u = str(raw or "").strip().lstrip("@").lower()
    u = u.strip("/")
    if u.startswith(BASE_URL):
        u = u[len(BASE_URL):].strip("/")
    return u if _USERNAME_RE.match(u) else ""


def parse_usernames(raw) -> tuple[list[str], list[str]]:
    """Accept a list or a comma/newline/space separated string.

    Returns (valid_unique_in_order, invalid_raw_tokens).
    """
    if raw is None:
        tokens: list[str] = []
    elif isinstance(raw, str):
        tokens = re.split(r"[,\s;]+", raw.strip())
    elif isinstance(raw, Iterable):
        tokens = [str(x) for x in raw]
    else:
        tokens = [str(raw)]

    valid: list[str] = []
    invalid: list[str] = []
    seen = set()
    for tok in tokens:
        if not tok.strip():
            continue
        u = normalize_username(tok)
        if not u:
            invalid.append(tok.strip())
        elif u not in seen:
            seen.add(u)
            valid.append(u)
    return valid, invalid


def not_following_back(followers, following) -> list[str]:
    """Accounts you follow that don't follow you back."""
    f_set, _ = parse_usernames(followers)
    g_set, _ = parse_usernames(following)
    fs = set(f_set)
    return sorted(u for u in g_set if u not in fs)


def mutuals(followers, following) -> list[str]:
    f_set, _ = parse_usernames(followers)
    g_set, _ = parse_usernames(following)
    return sorted(set(f_set) & set(g_set))


def fans(followers, following) -> list[str]:
    """Accounts that follow you but you don't follow back."""
    f_set, _ = parse_usernames(followers)
    g_set, _ = parse_usernames(following)
    gs = set(g_set)
    return sorted(u for u in f_set if u not in gs)


# ── Pure helpers: counts ────────────────────────────────────────────────────

def parse_count(text) -> int:
    """'1,234' -> 1234 ; '12.3K' -> 12300 ; '1.2M' -> 1200000 ; '' -> 0."""
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).strip().replace(",", "").replace(" ", "").replace("\u00a0", "")
    if not s:
        return 0
    m = re.match(r"^(-?\d+(?:\.\d+)?)([kmb])?$", s, re.IGNORECASE)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else 0
    num = float(m.group(1))
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(
        (m.group(2) or "").lower(), 1)
    return int(num * mult)


_META_RE = re.compile(
    r"([\d.,KMBkmb]+)\s+Followers,\s*([\d.,KMBkmb]+)\s+Following,\s*"
    r"([\d.,KMBkmb]+)\s+Posts", re.IGNORECASE)


def parse_profile_meta(description: str) -> dict:
    """Parse Instagram's <meta name=description> into follower/following/posts."""
    out = {"followers": 0, "following": 0, "posts": 0}
    m = _META_RE.search(str(description or ""))
    if m:
        out["followers"] = parse_count(m.group(1))
        out["following"] = parse_count(m.group(2))
        out["posts"] = parse_count(m.group(3))
    return out


# ── Pure helpers: captions ──────────────────────────────────────────────────

def _clean_tag(tag: str) -> str:
    return re.sub(r"[^0-9a-z_]", "", str(tag or "").lstrip("#").lower())


def compose_caption(text: str = "", hashtags=None, mentions=None) -> dict:
    """Build an Instagram-safe caption.

    Dedupes hashtags (max 30), normalizes #/@, and truncates to 2200 chars
    without cutting the hashtag block in half.
    """
    warnings: list[str] = []
    body = str(text or "").strip()

    if hashtags is None:
        tags_raw = []
    elif isinstance(hashtags, str):
        tags_raw = re.split(r"[,\s]+", hashtags.strip())
    else:
        tags_raw = list(hashtags)

    tags: list[str] = []
    seen = set()
    for t in tags_raw:
        c = _clean_tag(t)
        if c and c not in seen:
            seen.add(c)
            tags.append(c)
    if len(tags) > HASHTAG_MAX:
        warnings.append(f"Instagram allows {HASHTAG_MAX} hashtags; kept the first {HASHTAG_MAX}.")
        tags = tags[:HASHTAG_MAX]

    users, bad_users = parse_usernames(mentions or [])
    if bad_users:
        warnings.append(f"Ignored invalid mentions: {', '.join(bad_users)}")

    parts = [body]
    if users:
        parts.append(" ".join("@" + u for u in users))
    tag_block = " ".join("#" + t for t in tags)
    if tag_block:
        parts.append(tag_block)
    caption = "\n\n".join(p for p in parts if p)

    truncated = False
    if len(caption) > CAPTION_MAX:
        truncated = True
        warnings.append(f"Caption exceeded {CAPTION_MAX} characters and was shortened.")
        keep = CAPTION_MAX
        if tag_block:
            # Preserve the whole hashtag block, trim the prose instead.
            room = CAPTION_MAX - len(tag_block) - 2
            if room > 0:
                head = "\n\n".join(p for p in parts[:-1] if p)
                caption = head[:room].rstrip() + "\n\n" + tag_block
            else:
                caption = tag_block[:keep]
        else:
            caption = caption[:keep].rstrip()

    return {"caption": caption, "hashtags": tags, "mentions": users,
            "length": len(caption), "truncated": truncated, "warnings": warnings}


# ── Pure helpers: media ─────────────────────────────────────────────────────

def validate_media(paths, kind: str = "post") -> dict:
    """Validate files for post / carousel / reel / story.

    Returns {ok, kind, files, errors, warnings}. Never touches the network.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if paths is None:
        raw = []
    elif isinstance(paths, (str, Path)):
        raw = [paths]
    else:
        raw = list(paths)

    files: list[Path] = []
    for p in raw:
        if not str(p).strip():
            continue
        path = Path(str(p)).expanduser()
        if not path.exists():
            errors.append(f"Not found: {path}")
            continue
        if not path.is_file():
            errors.append(f"Not a file: {path}")
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTS | VIDEO_EXTS:
            errors.append(f"Unsupported type '{ext}': {path.name}")
            continue
        mb = path.stat().st_size / (1024 * 1024)
        limit = IMAGE_MAX_MB if ext in IMAGE_EXTS else VIDEO_MAX_MB
        if mb > limit:
            errors.append(f"{path.name} is {mb:.1f} MB (limit {limit} MB)")
            continue
        files.append(path)

    if not files and not errors:
        errors.append("No media file provided.")

    n_img = sum(1 for f in files if f.suffix.lower() in IMAGE_EXTS)
    n_vid = len(files) - n_img
    kind = (kind or "post").lower()

    if kind in ("reel", "video"):
        kind = "reel"
        if n_img and not n_vid:
            errors.append("A reel needs a video file (.mp4/.mov).")
        if len(files) > 1:
            errors.append("A reel takes exactly one video.")
    elif kind == "story":
        if len(files) > 1:
            errors.append("A story takes one photo or video.")
    elif kind == "carousel":
        if len(files) < 2:
            errors.append("A carousel needs at least 2 files.")
        if len(files) > CAROUSEL_MAX:
            errors.append(f"A carousel takes at most {CAROUSEL_MAX} files.")
        if n_img and n_vid:
            warnings.append("Mixed photo/video carousel — Instagram may reorder or reject it.")
    else:  # post / photo
        if len(files) > CAROUSEL_MAX:
            errors.append(f"Instagram takes at most {CAROUSEL_MAX} files per post.")
        elif len(files) > 1:
            kind = "carousel"
        elif n_vid:
            kind = "reel"
        else:
            kind = "post"

    return {"ok": not errors, "kind": kind, "files": [str(f) for f in files],
            "errors": errors, "warnings": warnings}


# ── Activity ledger (daily caps + spacing) ──────────────────────────────────

class ActivityLedger:
    """Persisted per-day action counters and last-action timestamps."""

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
    def _day(now: float) -> str:
        return datetime.fromtimestamp(now).date().isoformat()

    def count_today(self, kind: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return int(self.data["days"].get(self._day(now), {}).get(kind, 0))

    def counts_today(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        return dict(self.data["days"].get(self._day(now), {}))

    def check(self, kind: str, now: float | None = None) -> tuple[bool, str]:
        """(allowed, reason). Unlisted kinds are unlimited."""
        now = time.time() if now is None else now
        cap = DAILY_CAPS.get(kind)
        if cap is None:
            return True, ""
        used = self.count_today(kind, now)
        if used >= cap:
            return False, (f"Daily {kind} limit reached ({used}/{cap}). "
                           "This protects your account from action blocks — try again tomorrow.")
        gap = MIN_INTERVAL_S.get(kind, 0)
        last = float(self.data["last"].get(kind, 0))
        wait = gap - (now - last)
        if last and wait > 0:
            return False, f"Slow down — wait {int(wait) + 1}s before the next {kind}."
        return True, ""

    def record(self, kind: str, now: float | None = None):
        now = time.time() if now is None else now
        day = self.data["days"].setdefault(self._day(now), {})
        day[kind] = int(day.get(kind, 0)) + 1
        self.data["last"][kind] = now
        self.save()

    def summary(self, now: float | None = None) -> str:
        counts = self.counts_today(now)
        if not counts:
            return "No Instagram actions recorded today."
        lines = [f"  {k}: {counts[k]}/{DAILY_CAPS.get(k, '∞')}" for k in sorted(counts)]
        return "Today's Instagram activity:\n" + "\n".join(lines)


# ── Scheduled post queue ────────────────────────────────────────────────────

class PostQueue:
    """Local schedule of pending posts (memory/instagram_queue.json)."""

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

    def add(self, media, caption: str = "", when: float | None = None,
            kind: str = "post", now: float | None = None) -> dict:
        now = time.time() if now is None else now
        check = validate_media(media, kind)
        if not check["ok"]:
            return {"ok": False, "errors": check["errors"]}
        item = {
            "id": uuid.uuid4().hex[:8],
            "kind": check["kind"],
            "media": check["files"],
            "caption": caption,
            "when": float(when if when is not None else now),
            "status": "pending",
            "created": now,
        }
        self.items.append(item)
        self.save()
        return {"ok": True, "item": item}

    def list(self, status: str = "") -> list:
        if status:
            return [i for i in self.items if i.get("status") == status]
        return list(self.items)

    def due(self, now: float | None = None) -> list:
        now = time.time() if now is None else now
        return [i for i in self.items
                if i.get("status") == "pending" and float(i.get("when", 0)) <= now]

    def cancel(self, item_id: str) -> bool:
        for i in self.items:
            if i.get("id") == item_id and i.get("status") == "pending":
                i["status"] = "cancelled"
                self.save()
                return True
        return False

    def mark(self, item_id: str, status: str = "done"):
        for i in self.items:
            if i.get("id") == item_id:
                i["status"] = status
                self.save()
                return True
        return False

    def render(self) -> str:
        pending = self.list("pending")
        if not pending:
            return "No scheduled Instagram posts."
        lines = []
        for i in sorted(pending, key=lambda x: x.get("when", 0)):
            ts = datetime.fromtimestamp(float(i.get("when", 0))).strftime("%Y-%m-%d %H:%M")
            names = ", ".join(Path(m).name for m in i.get("media", []))
            lines.append(f"  [{i['id']}] {ts} — {i['kind']}: {names}")
        return f"Scheduled posts ({len(pending)}):\n" + "\n".join(lines)


# ── Report ──────────────────────────────────────────────────────────────────

def build_report(profile: dict | None = None, ledger: ActivityLedger | None = None,
                 queue: PostQueue | None = None, now: float | None = None) -> str:
    now = time.time() if now is None else now
    profile = profile or {}
    stamp = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    lines = [f"# Instagram report — {stamp}", ""]
    if profile:
        lines += ["## Profile", "",
                  f"- Handle: @{profile.get('username', '?')}",
                  f"- Followers: {profile.get('followers', 0):,}",
                  f"- Following: {profile.get('following', 0):,}",
                  f"- Posts: {profile.get('posts', 0):,}", ""]
    lines += ["## Activity today", ""]
    counts = ledger.counts_today(now) if ledger else {}
    if counts:
        lines += [f"- {k}: {counts[k]} / {DAILY_CAPS.get(k, 'unlimited')}"
                  for k in sorted(counts)]
    else:
        lines.append("- No actions recorded today.")
    lines += ["", "## Scheduled", ""]
    pending = queue.list("pending") if queue else []
    if pending:
        for i in sorted(pending, key=lambda x: x.get("when", 0)):
            ts = datetime.fromtimestamp(float(i.get("when", 0))).strftime("%Y-%m-%d %H:%M")
            lines.append(f"- `{i['id']}` {ts} — {i['kind']}")
    else:
        lines.append("- Nothing scheduled.")
    return "\n".join(lines) + "\n"


# ── Confirmation gate ───────────────────────────────────────────────────────

def require_confirm(parameters: dict, action: str) -> str | None:
    if parameters.get("dry_run"):
        return f"Dry run: would perform '{action}' — nothing was changed."
    if str(parameters.get("confirm", "")) != CONFIRM_TEXT:
        return (f"'{action}' changes your account or publishes publicly. "
                f"Call again with confirm='{CONFIRM_TEXT}' (or dry_run=true to preview).")
    return None


# ── Browser primitives (driver injected; no selenium import needed) ─────────

def _first(driver, selectors: list[str], timeout: float = 6.0):
    """First visible element matching any CSS selector, else None."""
    deadline = time.time() + timeout
    while True:
        for css in selectors:
            try:
                for el in driver.find_elements(CSS, css):
                    try:
                        if el.is_displayed():
                            return el
                    except Exception:
                        return el
            except Exception:
                pass
        if time.time() >= deadline:
            return None
        time.sleep(0.25)


def _click_text(driver, texts: list[str]) -> bool:
    """Click a button / role=button whose text matches one of `texts`."""
    expr = " or ".join(f"normalize-space()='{t}'" for t in texts)
    xpaths = [f"//button[{expr}]", f"//div[@role='button' and ({expr})]",
              f"//*[@role='button' and ({expr})]"]
    lowered = " or ".join(
        f"contains(translate(normalize-space(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        f"'abcdefghijklmnopqrstuvwxyz'),'{t.lower()}')" for t in texts)
    xpaths.append(f"//button[{lowered}]")
    xpaths.append(f"//div[@role='button' and ({lowered})]")
    for xp in xpaths:
        try:
            for el in driver.find_elements(XPATH, xp):
                try:
                    if el.is_displayed():
                        el.click()
                        return True
                except Exception:
                    pass
        except Exception:
            pass
    return False


def _dismiss(driver):
    """Close the usual 'Save info?' / 'Turn on notifications?' dialogs."""
    _click_text(driver, ["Not Now", "Not now", "Cancel", "OK"])


def _goto(driver, url: str):
    if not url.startswith("http"):
        url = BASE_URL + "/" + url.lstrip("/")
    driver.get(url)
    time.sleep(1.5)
    _dismiss(driver)


def _type_box(driver, text: str, selectors: list[str] | None = None):
    """Type into the last matching text box; return that element (or None).

    Returning the element lets callers press ENTER on the *same* box they
    typed into, instead of re-querying and possibly hitting a different one.
    """
    sels = selectors or ["div[contenteditable='true'][role='textbox']",
                         "textarea[aria-label]", "div[contenteditable='true']"]
    deadline = time.time() + 6
    while True:
        for css in sels:
            try:
                boxes = driver.find_elements(CSS, css)
                if boxes:
                    box = boxes[-1]
                    box.click()
                    box.send_keys(text)
                    return box
            except Exception:
                pass
        if time.time() >= deadline:
            return None
        time.sleep(0.25)


def _upload(driver, path: str) -> bool:
    try:
        inputs = driver.find_elements(CSS, "input[type='file']")
        if inputs:
            inputs[0].send_keys(str(Path(path).expanduser().resolve()))
            time.sleep(2.5)
            return True
    except Exception:
        pass
    return False


def _open_thread(driver, username: str) -> bool:
    """Open (or create) a DM thread with `username`."""
    _goto(driver, "/direct/new/")
    box = _first(driver, ["input[name='queryBox']", "input[placeholder*='Search']"])
    if box is None:
        return False
    box.send_keys(username)
    time.sleep(2.0)
    try:
        hits = driver.find_elements(XPATH, f"//*[contains(text(),'{username}')]")
        if not hits:
            return False
        hits[0].click()
        time.sleep(1.0)
    except Exception:
        return False
    return _click_text(driver, ["Chat", "Next"])


def _collect_handles(driver, scrolls: int = 5) -> list[str]:
    """Read handles from an open followers/following dialog (bounded)."""
    handles: list[str] = []
    seen = set()
    for _ in range(max(1, min(int(scrolls), LIST_SCROLL_MAX))):
        try:
            links = driver.find_elements(CSS, "div[role='dialog'] a[href^='/']")
            for a in links:
                href = a.get_attribute("href") or ""
                u = normalize_username(href.replace(BASE_URL, ""))
                if u and u not in seen:
                    seen.add(u)
                    handles.append(u)
                    if len(handles) >= LIST_RESULT_MAX:
                        return handles
            driver.execute_script(
                "var d=document.querySelector(\"div[role='dialog'] ul\");"
                "if(d){d.parentNode.scrollTop+=800;}")
        except Exception:
            break
        time.sleep(0.8)
    return handles


# ── Browser operations ──────────────────────────────────────────────────────

def op_inbox(driver, limit: int = 15) -> str:
    _goto(driver, "/direct/inbox/")
    try:
        threads = driver.find_elements(CSS, "a[href^='/direct/t/']")
    except Exception:
        threads = []
    if not threads:
        return "No DM threads visible (inbox may be empty or the layout changed)."
    lines = []
    for t in threads[:max(1, min(int(limit), 50))]:
        try:
            txt = " ".join((t.text or "").split())[:110]
            href = t.get_attribute("href") or ""
            lines.append(f"  • {txt}\n    {href}")
        except Exception:
            pass
    return f"📥 Inbox ({len(lines)} threads):\n" + "\n".join(lines)


def op_dm_read(driver, username: str = "", url: str = "", limit: int = 20) -> str:
    if url:
        _goto(driver, url)
    elif username:
        if not _open_thread(driver, normalize_username(username)):
            return f"Could not open a DM thread with @{username}."
    else:
        _goto(driver, "/direct/inbox/")
    time.sleep(1.5)
    texts: list[str] = []
    for css in ["div[role='row']", "div[role='gridcell']",
                "div[data-scope='messages_table'] div[dir='auto']"]:
        try:
            for el in driver.find_elements(CSS, css):
                t = " ".join((el.text or "").split())
                if t and t not in texts:
                    texts.append(t)
        except Exception:
            pass
        if texts:
            break
    if not texts:
        return "Could not read messages — the thread may be empty or the layout changed."
    tail = texts[-max(1, min(int(limit), 100)):]
    return "💬 Recent messages:\n" + "\n".join(f"  • {t[:200]}" for t in tail)


def op_dm_send(driver, username: str, message: str) -> str:
    u = normalize_username(username)
    if not u:
        return f"Invalid Instagram username: {username}"
    if not _open_thread(driver, u):
        return f"Could not open a DM thread with @{u}."
    box = _type_box(driver, message)
    if box is None:
        return "Could not find the message box."
    box.send_keys(ENTER)
    time.sleep(1.2)
    return f"✉️ DM sent to @{u}."


def op_dm_image(driver, username: str, image_path: str, message: str = "") -> str:
    u = normalize_username(username)
    if not u:
        return f"Invalid Instagram username: {username}"
    check = validate_media([image_path], "post")
    if not check["ok"]:
        return "Media problem: " + "; ".join(check["errors"])
    if Path(check["files"][0]).suffix.lower() not in IMAGE_EXTS:
        return "DM attachments here must be an image (.jpg/.png/.webp)."
    if not _open_thread(driver, u):
        return f"Could not open a DM thread with @{u}."
    if not _upload(driver, check["files"][0]):
        return "Could not find the DM attachment input."
    if message:
        _type_box(driver, message)
    if not _click_text(driver, ["Send"]):
        box = _first(driver, ["div[contenteditable='true'][role='textbox']"])
        if box is not None:
            box.send_keys(ENTER)
    time.sleep(1.5)
    return f"🖼️ Image sent to @{u}: {Path(check['files'][0]).name}"


def op_post(driver, media, caption: str = "", kind: str = "post") -> str:
    check = validate_media(media, kind)
    if not check["ok"]:
        return "Media problem: " + "; ".join(check["errors"])
    kind = check["kind"]
    files = check["files"]

    if kind == "story":
        return _post_story(driver, files[0])
    if kind == "reel":
        return _post_reel(driver, files[0], caption)

    _goto(driver, "/")
    created = False
    for css in ["svg[aria-label='New post']", "svg[aria-label='Create']",
                "a[href='/create/select/']"]:
        el = _first(driver, [css], timeout=1.5)
        if el is not None:
            try:
                el.click()
                created = True
                break
            except Exception:
                pass
    if not created:
        _goto(driver, "/create/select/")
    time.sleep(1.5)

    if not _upload(driver, files[0]):
        return "Could not find the upload input — Instagram's layout may have changed."

    # Additional carousel files.
    if len(files) > 1:
        for extra in files[1:]:
            _click_text(driver, ["Select multiple", "Add"])
            if not _upload(driver, extra):
                break
    for _ in range(2):
        _click_text(driver, ["Next"])
        time.sleep(1.0)
    if caption:
        _type_box(driver, caption)
    if _click_text(driver, ["Share"]):
        time.sleep(3.0)
        label = "carousel" if len(files) > 1 else "post"
        return f"📸 Published {label} ({len(files)} file(s))." + (
            f" Caption: {caption[:80]}" if caption else "")
    return "Upload prepared but the Share button wasn't found — finish it in the browser."


def _post_reel(driver, video: str, caption: str) -> str:
    _goto(driver, "/create/reel/")
    if not _upload(driver, video):
        _goto(driver, "/")
        el = _first(driver, ["svg[aria-label='New post']", "svg[aria-label='Create']"])
        if el is None:
            return "Could not open the reel composer."
        el.click()
        time.sleep(1.5)
        if not _upload(driver, video):
            return "Could not find the reel upload input."
    for _ in range(3):
        _click_text(driver, ["Next"])
        time.sleep(1.0)
    if caption:
        _type_box(driver, caption)
    if _click_text(driver, ["Share"]):
        time.sleep(3.5)
        return f"🎬 Reel published: {Path(video).name}"
    return "Reel prepared but Share wasn't found — finish it in the browser."


def _post_story(driver, media: str) -> str:
    _goto(driver, "/create/story/")
    if not _upload(driver, media):
        _goto(driver, "/")
        el = _first(driver, ["svg[aria-label='New story']", "a[href='/create/story/']"])
        if el is None:
            return "Could not open the story composer."
        el.click()
        time.sleep(1.5)
        if not _upload(driver, media):
            return "Could not find the story upload input."
    for label in ["Add to story", "Add to your story", "Share"]:
        if _click_text(driver, [label]):
            time.sleep(2.5)
            return f"📖 Story published: {Path(media).name}"
    return "Story prepared but the publish button wasn't found — finish it in the browser."


def op_follow(driver, username: str, unfollow: bool = False) -> str:
    u = normalize_username(username)
    if not u:
        return f"Invalid Instagram username: {username}"
    _goto(driver, f"/{u}/")
    if unfollow:
        if _click_text(driver, ["Following", "Requested"]):
            time.sleep(0.8)
            _click_text(driver, ["Unfollow"])
            return f"➖ Unfollowed @{u}."
        return f"Not following @{u} (or the button wasn't found)."
    if _click_text(driver, ["Follow"]):
        return f"➕ Followed @{u}."
    return f"Already following @{u}, or the Follow button wasn't found."


def op_follow_list(driver, username: str, which: str = "followers",
                   scrolls: int = 5) -> dict:
    u = normalize_username(username)
    if not u:
        return {"ok": False, "error": f"Invalid username: {username}", "handles": []}
    _goto(driver, f"/{u}/")
    if not _click_text(driver, [which.capitalize(), which]):
        # Fall back to the profile links.
        el = _first(driver, [f"a[href='/{u}/{which}/']"])
        if el is None:
            return {"ok": False, "error": f"Could not open the {which} list for @{u}.",
                    "handles": []}
        el.click()
        time.sleep(1.5)
    handles = _collect_handles(driver, scrolls)
    return {"ok": True, "handles": handles, "username": u, "which": which}


def op_requests(driver, accept: bool = True, username: str = "") -> str:
    _goto(driver, "/accounts/activity/")
    time.sleep(1.5)
    if username:
        u = normalize_username(username)
        if not u:
            return f"Invalid username: {username}"
    label = "Confirm" if accept else "Delete"
    if _click_text(driver, [label]):
        return f"{'✅ Accepted' if accept else '🗑️ Declined'} a follow request."
    return f"No '{label}' button found — there may be no pending follow requests."


def op_engage(driver, post_url: str, what: str = "like") -> str:
    if not post_url:
        return "Provide the post URL."
    _goto(driver, post_url)
    labels = {"like": ["Like"], "unlike": ["Unlike"], "save": ["Save"],
              "unsave": ["Remove", "Unsave"]}.get(what, ["Like"])
    for label in labels:
        el = _first(driver, [f"svg[aria-label='{label}']"], timeout=2.0)
        if el is not None:
            try:
                el.click()
            except Exception:
                parent = _first(driver, [f"button:has(svg[aria-label='{label}'])"], timeout=1.0)
                if parent is None:
                    continue
                parent.click()
            time.sleep(1.0)
            return f"{'❤️' if what == 'like' else '🔖'} {what.capitalize()} done."
    return f"Could not find the {what} button — it may already be applied."


def op_comment(driver, post_url: str, text: str) -> str:
    if not post_url or not text:
        return "Provide both the post URL and the comment text."
    _goto(driver, post_url)
    sels = ["textarea[aria-label='Add a comment…']", "textarea[placeholder*='comment']",
            "textarea[aria-label*='comment']"]
    box = _type_box(driver, text, sels)
    if box is None:
        return "Could not find the comment box — comments may be disabled."
    box.send_keys(ENTER)
    time.sleep(1.2)
    return f"💬 Comment posted: {text[:80]}"


def op_comments_read(driver, post_url: str, limit: int = 20) -> str:
    if not post_url:
        return "Provide the post URL."
    _goto(driver, post_url)
    texts: list[str] = []
    for css in ["ul li div[dir='auto']", "span[dir='auto']"]:
        try:
            for el in driver.find_elements(CSS, css):
                t = " ".join((el.text or "").split())
                if t and len(t) > 2 and t not in texts:
                    texts.append(t)
        except Exception:
            pass
        if texts:
            break
    if not texts:
        return "No comments found."
    return "💬 Comments:\n" + "\n".join(
        f"  • {t[:180]}" for t in texts[:max(1, min(int(limit), 100))])


def op_profile(driver, username: str) -> dict:
    u = normalize_username(username)
    if not u:
        return {"ok": False, "error": f"Invalid username: {username}"}
    _goto(driver, f"/{u}/")
    desc = ""
    title = ""
    try:
        el = _first(driver, ["meta[name='description']", "meta[property='og:description']"],
                    timeout=2.0)
        if el is not None:
            desc = el.get_attribute("content") or ""
    except Exception:
        pass
    try:
        el = _first(driver, ["meta[property='og:title']"], timeout=1.0)
        if el is not None:
            title = el.get_attribute("content") or ""
    except Exception:
        pass
    stats = parse_profile_meta(desc)
    return {"ok": True, "username": u, "title": title, "description": desc, **stats}


def op_edit_bio(driver, bio: str) -> str:
    _goto(driver, "/accounts/edit/")
    box = _first(driver, ["textarea#pepBio", "textarea[name='biography']", "textarea"])
    if box is None:
        return "Could not find the bio field."
    try:
        box.clear()
        box.send_keys(bio)
    except Exception as e:
        return f"Could not type the bio: {e}"
    if _click_text(driver, ["Submit", "Save"]):
        return "✅ Bio updated."
    return "Bio typed but Submit wasn't found — press Submit in the browser."


def op_set_avatar(driver, image_path: str) -> str:
    check = validate_media([image_path], "post")
    if not check["ok"]:
        return "Media problem: " + "; ".join(check["errors"])
    if Path(check["files"][0]).suffix.lower() not in IMAGE_EXTS:
        return "Profile photo must be an image."
    _goto(driver, "/accounts/edit/")
    if not _upload(driver, check["files"][0]):
        if not _click_text(driver, ["Change profile photo", "Change Profile Photo"]):
            return "Could not find the profile-photo control."
        if not _upload(driver, check["files"][0]):
            return "Could not find the photo upload input."
    return f"🖼️ Profile photo updated: {Path(check['files'][0]).name}"


def op_my_posts(driver, username: str, limit: int = 12) -> str:
    u = normalize_username(username)
    if not u:
        return f"Invalid username: {username}"
    _goto(driver, f"/{u}/")
    urls: list[str] = []
    try:
        for a in driver.find_elements(CSS, "a[href*='/p/'], a[href*='/reel/']"):
            href = a.get_attribute("href") or ""
            if href and href not in urls:
                urls.append(href)
    except Exception:
        pass
    if not urls:
        return f"No posts found for @{u}."
    return f"🗂️ Recent posts for @{u}:\n" + "\n".join(
        f"  • {x}" for x in urls[:max(1, min(int(limit), 60))])


# ── Action → rate-limit kind ────────────────────────────────────────────────

_LIMIT_KIND = {
    "follow": "follow", "follow_many": "follow",
    "unfollow": "unfollow",
    "dm": "dm", "dm_image": "dm", "dm_many": "dm",
    "comment": "comment",
    "like": "like", "unlike": "like",
    "post": "post", "carousel": "post", "reel": "post", "run_due": "post",
    "story": "story",
}

MUTATING = set(_LIMIT_KIND) | {
    "save", "unsave", "edit_bio", "set_avatar", "requests", "logout",
}

# Aliases are resolved BEFORE the confirm/rate-limit gate, so a synonym can
# never slip past it.
_ALIASES = {
    "message": "dm", "text": "dm", "send_dm": "dm",
    "dm_photo": "dm_image", "send_image": "dm_image",
    "photo": "post", "upload": "post", "post_photo": "post",
    "video": "reel", "post_video": "reel",
    "post_story": "story", "unfollow_many": "unfollow",
}


# ── Dispatcher ──────────────────────────────────────────────────────────────

def instagram_manager(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    action = _ALIASES.get(action, action)
    scrolls = int(params.get("scrolls", 5))

    # ── No browser needed ───────────────────────────────────────────────
    if action in ("help", "capabilities"):
        return (
            "📸 Instagram Manager — what I can do:\n"
            "  Messages: inbox, dm_read, dm, dm_image, dm_many\n"
            "  Publish:  post, carousel, reel, story, schedule, queue, unschedule, run_due\n"
            "  Follow:   follow, unfollow, follow_many, followers, following,\n"
            "            not_following_back, mutuals, fans, requests\n"
            "  Engage:   like, unlike, comment, comments, save\n"
            "  Profile:  profile, edit_bio, set_avatar, my_posts\n"
            "  Insight:  activity, report, status, login, logout\n"
            f"Account-changing actions need confirm='{CONFIRM_TEXT}'. "
            "Daily caps keep your account safe."
        )

    if action == "setup":
        return _ig()._setup_credentials(params)

    if action == "activity":
        return ActivityLedger().summary()

    if action == "queue":
        return PostQueue().render()

    if action == "report":
        prof = None
        if params.get("username"):
            driver, err = _session(params, player)
            if driver is not None and not err:
                prof = op_profile(driver, params["username"])
                try:
                    driver.quit()
                except Exception:
                    pass
        text = build_report(prof, ActivityLedger(), PostQueue())
        if params.get("save"):
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            out = REPORT_DIR / f"instagram_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            out.write_text(text, encoding="utf-8")
            return f"📊 Report saved to {out}\n\n{text}"
        return text

    if action == "schedule":
        cap = compose_caption(params.get("caption", ""), params.get("hashtags"),
                              params.get("mentions"))
        when = params.get("when")
        try:
            when_ts = float(when) if when not in (None, "") else None
        except (TypeError, ValueError):
            return ("'when' must be a Unix timestamp. Ask me to schedule it and I'll "
                    "compute the time, or pass seconds since epoch.")
        res = PostQueue().add(params.get("media") or params.get("media_path")
                              or params.get("path"), cap["caption"],
                              when_ts, params.get("kind", "post"))
        if not res["ok"]:
            return "Could not schedule: " + "; ".join(res["errors"])
        item = res["item"]
        ts = datetime.fromtimestamp(item["when"]).strftime("%Y-%m-%d %H:%M")
        warn = ("\n⚠️ " + " ".join(cap["warnings"])) if cap["warnings"] else ""
        return f"🗓️ Scheduled [{item['id']}] for {ts} ({item['kind']}).{warn}"

    if action == "unschedule":
        item_id = str(params.get("id", "")).strip()
        if not item_id:
            return "Which scheduled post? Give me its id (see 'queue')."
        return (f"🗑️ Cancelled [{item_id}]." if PostQueue().cancel(item_id)
                else f"No pending post with id '{item_id}'.")

    if action in ("not_following_back", "mutuals", "fans"):
        followers = params.get("followers")
        following = params.get("following")
        driver = None
        if followers is None or following is None:
            u = params.get("username", "")
            if not u:
                return ("Give me a username to read the lists from, or pass "
                        "followers/following lists directly.")
            driver, err = _session(params, player)
            if err:
                return err
            if followers is None:
                followers = op_follow_list(driver, u, "followers", scrolls)["handles"]
            if following is None:
                following = op_follow_list(driver, u, "following", scrolls)["handles"]
            try:
                driver.quit()
            except Exception:
                pass
        fn = {"not_following_back": not_following_back,
              "mutuals": mutuals, "fans": fans}[action]
        result = fn(followers, following)
        titles = {"not_following_back": "Don't follow you back",
                  "mutuals": "Mutual follows", "fans": "Follow you, you don't follow back"}
        if not result:
            return f"{titles[action]}: none found."
        return f"{titles[action]} ({len(result)}):\n" + "\n".join(f"  @{x}" for x in result)

    # ── Browser-backed ──────────────────────────────────────────────────
    if action in MUTATING:
        gate = require_confirm(params, action)
        if gate:
            return gate
        kind = _LIMIT_KIND.get(action)
        if kind:
            ok, reason = ActivityLedger().check(kind)
            if not ok:
                return f" {reason}"

    driver, err = _session(params, player)
    if err:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        return err

    ledger = ActivityLedger()
    try:
        _log(player, f"[IG] {action}")

        if action == "login":
            return "Instagram session is active."
        if action == "status":
            return "✅ Instagram connected."
        if action == "logout":
            _goto(driver, "/accounts/logout/")
            return "Logged out of Instagram."

        # Messages
        if action == "inbox":
            return op_inbox(driver, int(params.get("limit", 15)))
        if action == "dm_read":
            return op_dm_read(driver, params.get("username", ""), params.get("url", ""),
                              int(params.get("limit", 20)))
        if action in ("dm", "message", "text"):
            msg = params.get("message") or params.get("text", "")
            if not msg:
                return "What should the message say?"
            out = op_dm_send(driver, params.get("username", ""), msg)
            if out.startswith("✉️"):
                ledger.record("dm")
                _say(speak, "Message sent.")
            return out
        if action in ("dm_image", "dm_photo"):
            out = op_dm_image(driver, params.get("username", ""),
                              params.get("media") or params.get("image_path")
                              or params.get("path", ""),
                              params.get("message", ""))
            if out.startswith("🖼️"):
                ledger.record("dm")
            return out
        if action == "dm_many":
            users, bad = parse_usernames(params.get("usernames"))
            msg = params.get("message") or params.get("text", "")
            if not users or not msg:
                return "Provide usernames (list) and a message."
            if len(users) > BATCH_MAX:
                return (f"I cap batches at {BATCH_MAX} recipients to protect your account. "
                        f"You gave {len(users)} — split it up.")
            lines, sent = [], 0
            for u in users:
                ok, reason = ledger.check("dm")
                if not ok:
                    lines.append(f"  ⏳ stopped: {reason}")
                    break
                r = op_dm_send(driver, u, msg)
                lines.append(f"  {r}")
                if r.startswith("✉️"):
                    ledger.record("dm")
                    sent += 1
            if bad:
                lines.append(f"  skipped invalid: {', '.join(bad)}")
            return f"✉️ Sent {sent}/{len(users)} DMs:\n" + "\n".join(lines)

        # Publishing
        if action in ("post", "photo", "carousel", "reel", "video", "story"):
            kind = {"photo": "post", "video": "reel"}.get(action, action)
            cap = compose_caption(params.get("caption", ""), params.get("hashtags"),
                                  params.get("mentions"))
            media = (params.get("media") or params.get("media_path")
                     or params.get("image_path") or params.get("video_path")
                     or params.get("path"))
            out = op_post(driver, media, cap["caption"], kind)
            if out.startswith(("📸", "🎬", "📖")):
                ledger.record("story" if kind == "story" else "post")
                _say(speak, "Posted to Instagram.")
            if cap["warnings"]:
                out += "\n⚠️ " + " ".join(cap["warnings"])
            return out
        if action == "run_due":
            q = PostQueue()
            due = q.due()
            if not due:
                return "Nothing is due to post right now."
            lines, done = [], 0
            for item in due:
                ok, reason = ledger.check("post")
                if not ok:
                    lines.append(f"  ⏳ stopped: {reason}")
                    break
                r = op_post(driver, item["media"], item.get("caption", ""), item["kind"])
                lines.append(f"  [{item['id']}] {r}")
                if r.startswith(("📸", "🎬", "📖")):
                    q.mark(item["id"], "done")
                    ledger.record("post")
                    done += 1
                else:
                    q.mark(item["id"], "failed")
            return f"🗓️ Published {done}/{len(due)} scheduled posts:\n" + "\n".join(lines)

        # Following
        if action in ("follow", "unfollow"):
            out = op_follow(driver, params.get("username", ""), action == "unfollow")
            if out.startswith(("➕", "➖")):
                ledger.record(action)
            return out
        if action == "follow_many":
            users, bad = parse_usernames(params.get("usernames"))
            if not users:
                return "Provide usernames to follow (list or comma-separated)."
            if len(users) > BATCH_MAX:
                return (f"I cap batches at {BATCH_MAX} accounts per call. "
                        f"You gave {len(users)} — split it up.")
            lines, done = [], 0
            for u in users:
                ok, reason = ledger.check("follow")
                if not ok:
                    lines.append(f"  ⏳ stopped: {reason}")
                    break
                r = op_follow(driver, u)
                lines.append(f"  {r}")
                if r.startswith("➕"):
                    ledger.record("follow")
                    done += 1
            if bad:
                lines.append(f"  skipped invalid: {', '.join(bad)}")
            return f"➕ Followed {done}/{len(users)}:\n" + "\n".join(lines)
        if action in ("followers", "following"):
            res = op_follow_list(driver, params.get("username", ""), action, scrolls)
            if not res["ok"]:
                return res["error"]
            hs = res["handles"]
            return (f"@{res['username']} {action} ({len(hs)} read"
                    f"{', list may continue' if len(hs) >= LIST_RESULT_MAX else ''}):\n"
                    + "\n".join(f"  @{h}" for h in hs))
        if action == "requests":
            accept = str(params.get("accept", "true")).lower() not in ("false", "0", "no")
            return op_requests(driver, accept, params.get("username", ""))

        # Engagement
        if action in ("like", "unlike", "save", "unsave"):
            out = op_engage(driver, params.get("url", ""), action)
            if "done" in out:
                if action in ("like", "unlike"):
                    ledger.record("like")
            return out
        if action == "comment":
            out = op_comment(driver, params.get("url", ""),
                             params.get("text") or params.get("comment", ""))
            if out.startswith("💬"):
                ledger.record("comment")
            return out
        if action == "comments":
            return op_comments_read(driver, params.get("url", ""),
                                    int(params.get("limit", 20)))

        # Profile
        if action == "profile":
            res = op_profile(driver, params.get("username", ""))
            if not res["ok"]:
                return res["error"]
            return (f"👤 @{res['username']} {res['title']}\n"
                    f"  Followers: {res['followers']:,}\n"
                    f"  Following: {res['following']:,}\n"
                    f"  Posts:     {res['posts']:,}")
        if action == "edit_bio":
            bio = params.get("bio") or params.get("text", "")
            if not bio:
                return "What should the new bio say?"
            return op_edit_bio(driver, bio)
        if action == "set_avatar":
            return op_set_avatar(driver, params.get("media")
                                 or params.get("image_path") or params.get("path", ""))
        if action == "my_posts":
            return op_my_posts(driver, params.get("username", ""),
                               int(params.get("limit", 12)))

        return f"Unknown Instagram action '{action}'. Say 'instagram help' for the list."
    except Exception as e:
        return f"Instagram manager '{action}' failed: {e}"
    finally:
        if not params.get("keep_open"):
            try:
                driver.quit()
            except Exception:
                pass
