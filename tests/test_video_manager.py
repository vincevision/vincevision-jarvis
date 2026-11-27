"""Offline tests for the YouTube + TikTok video manager (no browser)."""

import pytest

from actions import video_manager as vm


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.t = start

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(vm, "time", c)
    return c


@pytest.fixture
def calls(monkeypatch):
    """Record every browser_control call; return canned successes."""
    log = []

    def fake(params, player=None):
        log.append(params)
        a = params.get("action")
        if a == "upload":
            return "Attached 1 file(s)"
        if a == "get_text":
            return "Views 1,234\nSubscribers 56"
        if a == "smart_click":
            return f"Clicked button: '{params.get('description')}'"
        return "ok"

    monkeypatch.setattr(vm, "_browser", fake)
    return log


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(vm, "QUEUE_PATH", tmp_path / "queue.json")
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"x" * 2048)
    t = tmp_path / "thumb.jpg"
    t.write_bytes(b"y" * 1024)
    return {"video": v, "thumb": t}


# ── platform detection ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("youtube", "youtube"), ("YT", "youtube"),
    ("https://youtube.com/watch?v=1", "youtube"),
    ("youtu.be/abc", "youtube"), ("tiktok", "tiktok"), ("TT", "tiktok"),
    ("https://www.tiktok.com/@me", "tiktok"), ("vimeo", ""), ("", ""),
])
def test_detect_platform(raw, expected):
    assert vm.detect_platform(raw) == expected


# ── tags ────────────────────────────────────────────────────────────────────

def test_parse_tags_dedupe():
    assert vm.parse_tags("travel, #Travel, food") == ["travel", "food"]


def test_parse_tags_list_and_newlines():
    assert vm.parse_tags(["a", "b", "a"]) == ["a", "b"]
    assert vm.parse_tags("a\nb") == ["a", "b"]


def test_parse_tags_empty():
    assert vm.parse_tags(None) == []


def test_extract_hashtags():
    assert vm.extract_hashtags("nice #sunset and #travel") == ["sunset", "travel"]


# ── media validation ────────────────────────────────────────────────────────

def test_validate_video_ok(paths):
    assert vm.validate_video(paths["video"], "youtube")["ok"]


def test_validate_video_missing(tmp_path):
    r = vm.validate_video(tmp_path / "no.mp4")
    assert not r["ok"] and "Not found" in r["errors"][0]


def test_validate_video_bad_ext(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"x")
    assert not vm.validate_video(p)["ok"]


def test_validate_video_none():
    assert not vm.validate_video("")["ok"]


def test_validate_video_size_cap(paths, monkeypatch):
    monkeypatch.setitem(vm.VIDEO_MAX_MB, "tiktok", 0)
    r = vm.validate_video(paths["video"], "tiktok")
    assert not r["ok"] and "limit" in r["errors"][0]


def test_validate_thumbnail_optional():
    assert vm.validate_thumbnail("")["ok"]


def test_validate_thumbnail_ok(paths):
    assert vm.validate_thumbnail(paths["thumb"])["ok"]


def test_validate_thumbnail_bad_type(paths):
    assert not vm.validate_thumbnail(paths["video"])["ok"]


def test_validate_thumbnail_too_big(paths, monkeypatch):
    monkeypatch.setattr(vm, "THUMB_MAX_MB", 0)
    assert not vm.validate_thumbnail(paths["thumb"])["ok"]


# ── metadata validation ─────────────────────────────────────────────────────

def test_metadata_ok():
    r = vm.validate_metadata("youtube", "My title", "desc", "a,b", "unlisted")
    assert r["ok"] and r["privacy"] == "unlisted" and r["tags"] == ["a", "b"]


def test_metadata_requires_title():
    assert not vm.validate_metadata("youtube", "")["ok"]


def test_metadata_youtube_title_limit():
    r = vm.validate_metadata("youtube", "x" * 101)
    assert not r["ok"] and "100" in r["errors"][0]


def test_metadata_tiktok_caption_longer_limit():
    r = vm.validate_metadata("tiktok", "x" * 160)
    assert r["ok"] and r["warnings"]


def test_metadata_description_limit():
    assert not vm.validate_metadata("youtube", "t", "d" * 5001)["ok"]


def test_metadata_privacy_invalid():
    r = vm.validate_metadata("youtube", "t", privacy="secret")
    assert not r["ok"] and "privacy must be" in r["errors"][0]


def test_metadata_tiktok_privacy_friends():
    assert vm.validate_metadata("tiktok", "t", privacy="friends")["ok"]


def test_metadata_youtube_rejects_friends():
    assert not vm.validate_metadata("youtube", "t", privacy="friends")["ok"]


def test_metadata_defaults_public():
    assert vm.validate_metadata("youtube", "t")["privacy"] == "public"


def test_metadata_tag_count_trim():
    r = vm.validate_metadata("youtube", "t", tags=[f"tag{i}" for i in range(40)])
    assert len(r["tags"]) == 30 and r["warnings"]


def test_metadata_tag_chars_trim():
    r = vm.validate_metadata("youtube", "t", tags=["x" * 200, "y" * 200, "z" * 200])
    assert len(", ".join(r["tags"])) <= 500
    assert any("trimmed" in w for w in r["warnings"])


def test_describe_plan():
    meta = vm.validate_metadata("youtube", "Title", "Desc", "a", "private")
    plan = vm.describe_plan(meta, "/tmp/v.mp4", "/tmp/t.jpg")
    assert "Youtube" in plan and "Title" in plan and "private" in plan


# ── ledger ─────────────────────────────────────────────────────────────────

def test_ledger_cap(tmp_path, monkeypatch):
    monkeypatch.setitem(vm.DAILY_CAPS, "upload", 1)
    led = vm.VideoLedger(tmp_path / "s.json")
    led.record("upload", 1000.0)
    ok, reason = led.check("upload", 2000.0)
    assert not ok and "Daily upload limit" in reason


def test_ledger_spacing(tmp_path):
    led = vm.VideoLedger(tmp_path / "s.json")
    led.record("reply", 1000.0)
    assert not led.check("reply", 1001.0)[0]
    assert led.check("reply", 1000.0 + vm.MIN_INTERVAL_S["reply"] + 1)[0]


def test_ledger_unlimited_kind(tmp_path):
    assert vm.VideoLedger(tmp_path / "s.json").check("whatever", 1.0) == (True, "")


def test_ledger_persist_and_summary(tmp_path):
    p = tmp_path / "s.json"
    vm.VideoLedger(p).record("like", 1_700_000_000.0)
    assert "like: 1/100" in vm.VideoLedger(p).summary(1_700_000_000.0)


def test_ledger_corrupt(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("bad")
    assert vm.VideoLedger(p).counts_today() == {}


# ── upload queue ────────────────────────────────────────────────────────────

def test_queue_add(paths):
    q = vm.UploadQueue(paths["video"].parent / "q.json")
    r = q.add("youtube", paths["video"], "Title", when=2000.0, now=1000.0)
    assert r["ok"] and r["item"]["platform"] == "youtube"
    assert "Scheduled uploads (1)" in q.render()


def test_queue_rejects_bad_title(paths):
    q = vm.UploadQueue(paths["video"].parent / "q.json")
    assert not q.add("youtube", paths["video"], "")["ok"]


def test_queue_rejects_missing_video(tmp_path):
    q = vm.UploadQueue(tmp_path / "q.json")
    assert not q.add("youtube", tmp_path / "no.mp4", "T")["ok"]


def test_queue_due_and_cancel(paths):
    q = vm.UploadQueue(paths["video"].parent / "q.json")
    item = q.add("youtube", paths["video"], "T", when=1500.0, now=1000.0)["item"]
    assert q.due(now=1200.0) == []
    assert len(q.due(now=1600.0)) == 1
    assert q.cancel(item["id"])
    assert q.due(now=1600.0) == []


def test_queue_mark_done(paths):
    q = vm.UploadQueue(paths["video"].parent / "q.json")
    item = q.add("youtube", paths["video"], "T", when=1000.0, now=900.0)["item"]
    q.mark(item["id"], "done")
    assert q.due(now=2000.0) == []


def test_queue_empty_render(tmp_path):
    assert "No scheduled" in vm.UploadQueue(tmp_path / "q.json").render()


def test_build_report(paths):
    led = vm.VideoLedger(paths["video"].parent / "s.json")
    led.record("upload", 1_700_000_000.0)
    q = vm.UploadQueue(paths["video"].parent / "q.json")
    q.add("tiktok", paths["video"], "Clip", when=1_700_000_900.0, now=1_700_000_000.0)
    text = vm.build_report(led, q, now=1_700_000_100.0)
    assert "# Video studio report" in text
    assert "upload: 1 / 10" in text and "tiktok" in text


def test_build_report_empty():
    text = vm.build_report(now=1_700_000_000.0)
    assert "No actions recorded" in text and "Nothing scheduled" in text


# ── confirm gate ────────────────────────────────────────────────────────────

def test_confirm_required():
    assert vm.CONFIRM_TEXT in vm.require_confirm({}, "upload")


def test_confirm_ok():
    assert vm.require_confirm({"confirm": vm.CONFIRM_TEXT}, "upload") is None


def test_dry_run_returns_none():
    assert vm.require_confirm({"dry_run": True}, "upload") is None


# ── browser operations ──────────────────────────────────────────────────────

def test_op_upload_youtube(calls, paths):
    meta = vm.validate_metadata("youtube", "My video", "desc", "a,b", "unlisted")
    out = vm.op_upload("youtube", str(paths["video"]), meta, str(paths["thumb"]))
    assert out.startswith("🎬") and "YouTube" in out
    assert any(c["action"] == "go_to" and "studio.youtube" in c["url"] for c in calls)
    assert sum(1 for c in calls if c["action"] == "upload") == 2   # video + thumbnail
    assert any(c.get("description") == "Unlisted" for c in calls)


def test_op_upload_tiktok(calls, paths):
    meta = vm.validate_metadata("tiktok", "My clip", tags=["funny"])
    out = vm.op_upload("tiktok", str(paths["video"]), meta)
    assert out.startswith("🎬") and "TikTok" in out
    typed = [c for c in calls if c["action"] == "type"]
    assert typed and "#funny" in typed[0]["text"]


def test_op_upload_failure(monkeypatch, paths):
    monkeypatch.setattr(vm, "_browser", lambda p, player=None: "Upload failed: nope")
    meta = vm.validate_metadata("youtube", "T")
    assert "Upload failed" in vm.op_upload("youtube", str(paths["video"]), meta)


def test_op_comments(calls):
    out = vm.op_comments("youtube", "https://youtu.be/x")
    assert "Comments page" in out and "Views" in out


def test_op_comments_no_url(calls):
    assert "URL" in vm.op_comments("youtube", "")


def test_op_reply(calls):
    assert vm.op_reply("youtube", "https://youtu.be/x", "thanks!").startswith("💬")


def test_op_reply_missing(calls):
    assert "Provide" in vm.op_reply("youtube", "", "")


def test_op_like(calls):
    assert vm.op_like("youtube", "https://youtu.be/x").startswith("❤️")


def test_op_subscribe_youtube(calls):
    assert "Subscribe" in vm.op_subscribe("youtube", "https://youtube.com/@x")


def test_op_subscribe_tiktok(calls):
    assert "Follow" in vm.op_subscribe("tiktok", "https://tiktok.com/@x")


def test_op_playlist_add(calls):
    assert "playlist 'Watch later'" in vm.op_playlist_add("https://youtu.be/x", "Watch later")


def test_op_playlist_missing(calls):
    assert "Provide" in vm.op_playlist_add("", "")


def test_op_analytics(calls):
    out = vm.op_analytics("youtube")
    assert "analytics" in out.lower() and "Views" in out


# ── dispatcher ──────────────────────────────────────────────────────────────

def test_dispatch_help():
    assert "Video Manager" in vm.video_manager({"action": "help"})


def test_dispatch_unknown(calls, paths):
    assert "Unknown video action" in vm.video_manager({"action": "bogus"})


def test_dispatch_upload_needs_confirm(calls, paths):
    out = vm.video_manager({"action": "upload", "video": str(paths["video"]), "title": "T"})
    assert vm.CONFIRM_TEXT in out


def test_dispatch_dry_run_plan(calls, paths):
    out = vm.video_manager({"action": "upload", "video": str(paths["video"]),
                            "title": "T", "dry_run": True})
    assert "Dry run" in out and "Title:" in out
    assert not any(c["action"] == "upload" for c in calls)


def test_dispatch_upload_validates_first(calls, paths):
    out = vm.video_manager({"action": "upload", "video": str(paths["video"]),
                            "title": "x" * 200, "confirm": vm.CONFIRM_TEXT})
    assert "Upload blocked" in out
    assert not any(c["action"] == "upload" for c in calls)


def test_dispatch_upload_records(calls, paths):
    out = vm.video_manager({"action": "upload", "platform": "youtube",
                            "video": str(paths["video"]), "title": "T",
                            "confirm": vm.CONFIRM_TEXT})
    assert out.startswith("🎬")
    assert vm.VideoLedger().count_today("upload") == 1


def test_dispatch_upload_rate_limited(calls, paths):
    p = {"action": "upload", "video": str(paths["video"]), "title": "T",
         "confirm": vm.CONFIRM_TEXT}
    vm.video_manager(p)
    assert "Slow down" in vm.video_manager(p)


def test_dispatch_schedule_and_queue(calls, paths):
    out = vm.video_manager({"action": "schedule", "platform": "tiktok",
                            "video": str(paths["video"]), "title": "Later",
                            "when": 1_700_000_000})
    assert "Scheduled [" in out
    assert "Scheduled uploads (1)" in vm.video_manager({"action": "queue"})


def test_dispatch_schedule_bad_when(calls, paths):
    out = vm.video_manager({"action": "schedule", "video": str(paths["video"]),
                            "title": "T", "when": "friday"})
    assert "Unix timestamp" in out


def test_dispatch_unschedule(calls, paths):
    vm.video_manager({"action": "schedule", "video": str(paths["video"]),
                      "title": "T", "when": 1_700_000_000})
    item = vm.UploadQueue().list()[0]
    assert "Cancelled" in vm.video_manager({"action": "unschedule", "id": item["id"]})


def test_dispatch_unschedule_no_id(calls, paths):
    assert "Which upload" in vm.video_manager({"action": "unschedule"})


def test_dispatch_run_due_nothing(calls, paths):
    assert "Nothing is due" in vm.video_manager({"action": "run_due",
                                                 "confirm": vm.CONFIRM_TEXT})


def test_dispatch_run_due_publishes(calls, paths, clock):
    clock.t = 2_000_000_000.0
    vm.video_manager({"action": "schedule", "video": str(paths["video"]),
                      "title": "T", "when": 1_999_999_000})
    out = vm.video_manager({"action": "run_due", "confirm": vm.CONFIRM_TEXT})
    assert "Published 1/1" in out
    assert vm.UploadQueue().list("done")


def test_dispatch_reply_records(calls, paths):
    out = vm.video_manager({"action": "reply", "url": "https://youtu.be/x",
                            "text": "thanks", "confirm": vm.CONFIRM_TEXT})
    assert out.startswith("💬")
    assert vm.VideoLedger().count_today("reply") == 1


def test_dispatch_analytics(calls, paths):
    assert "analytics" in vm.video_manager({"action": "analytics"}).lower()


def test_dispatch_activity(calls, paths):
    assert "No video actions" in vm.video_manager({"action": "activity"})


def test_dispatch_report(calls, paths):
    assert "# Video studio report" in vm.video_manager({"action": "report"})
