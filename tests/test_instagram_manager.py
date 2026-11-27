"""Offline tests for the Instagram Manager.

No network, no browser, no selenium: browser operations receive a FakeDriver,
and the session factory is monkeypatched. Covers caption/media validation,
username maths, the rate-limit ledger, the schedule queue, the confirmation
gate, and the browser operations' selector logic.
"""

import json
import time

import pytest

from actions import instagram_manager as im


# ── Fakes ───────────────────────────────────────────────────────────────────

class FakeElement:
    def __init__(self, text="", attrs=None, label=""):
        self.text = text
        self.attrs = attrs or {}
        self.label = label
        self.keys: list[str] = []
        self.clicks = 0
        self.cleared = 0

    def is_displayed(self):
        return True

    def click(self):
        self.clicks += 1

    def send_keys(self, value):
        self.keys.append(value)

    def clear(self):
        self.cleared += 1

    def get_attribute(self, name):
        return self.attrs.get(name)


class FakeDriver:
    """Minimal WebDriver stand-in.

    css_map: {selector: [FakeElement]}
    buttons: {label: FakeElement}  (matched for XPath text queries)
    """

    def __init__(self, css_map=None, buttons=None):
        self.css_map = css_map or {}
        self.buttons = buttons or {}
        self.urls: list[str] = []
        self.scripts: list[str] = []
        self.quit_called = 0
        self.current_url = im.BASE_URL + "/"

    def get(self, url):
        self.urls.append(url)
        self.current_url = url

    def find_elements(self, by, value):
        if by == im.CSS:
            return list(self.css_map.get(value, []))
        if by == im.XPATH:
            import re
            labels = re.findall(r"'([^']+)'", value)
            out = []
            for label, el in self.buttons.items():
                if any(l == label or l.lower() in label.lower() for l in labels):
                    out.append(el)
            return out
        return []

    def execute_script(self, script, *args):
        self.scripts.append(script)

    def quit(self):
        self.quit_called += 1


class FakeClock:
    """Virtual clock: sleep() advances time instead of blocking.

    Keeps the polling loops instant *and* deterministic — patching sleep to a
    no-op would turn them into real-time busy-waits.
    """

    def __init__(self, start=1_700_000_000.0):
        self.t = start

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += float(seconds)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(im, "time", FakeClock())


@pytest.fixture
def session(monkeypatch, no_sleep):
    """Route _session() to a FakeDriver and isolate persisted state."""
    holder = {}

    def _install(driver, tmp_path):
        holder["driver"] = driver
        monkeypatch.setattr(im, "_session", lambda p, player=None: (driver, None))
        monkeypatch.setattr(im, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(im, "QUEUE_PATH", tmp_path / "queue.json")
        return driver

    return _install


# ── usernames ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("@Some.User", "some.user"),
    ("  alice  ", "alice"),
    ("bob/", "bob"),
    ("https://www.instagram.com/carol/", "carol"),
    ("/bob/", "bob"),
    ("bad name", ""),
    ("way_too_long_" + "x" * 40, ""),
    ("", ""),
    (None, ""),
])
def test_normalize_username(raw, expected):
    assert im.normalize_username(raw) == expected


def test_parse_usernames_dedupe_and_order():
    valid, bad = im.parse_usernames("@alice, bob @alice\ncarol; bad name")
    assert valid == ["alice", "bob", "carol", "bad", "name"]
    assert bad == []


def test_parse_usernames_list_and_invalid():
    valid, bad = im.parse_usernames(["@ok", "not valid!", ""])
    assert valid == ["ok"]
    assert bad == ["not valid!"]


def test_parse_usernames_empty():
    assert im.parse_usernames(None) == ([], [])
    assert im.parse_usernames("") == ([], [])


def test_not_following_back():
    assert im.not_following_back(["a", "b"], ["b", "c", "d"]) == ["c", "d"]


def test_mutuals():
    assert im.mutuals(["a", "b", "c"], ["b", "c", "d"]) == ["b", "c"]


def test_fans():
    assert im.fans(["a", "b"], ["b"]) == ["a"]


# ── counts / profile meta ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1,234", 1234), ("12.3K", 12300), ("1.2M", 1200000), ("2B", 2000000000),
    ("567", 567), ("", 0), (None, 0), (42, 42), ("1 234", 1234),
])
def test_parse_count(raw, expected):
    assert im.parse_count(raw) == expected


def test_parse_profile_meta():
    d = "1,234 Followers, 567 Following, 89 Posts - See Instagram photos from X (@x)"
    assert im.parse_profile_meta(d) == {"followers": 1234, "following": 567, "posts": 89}


def test_parse_profile_meta_missing():
    assert im.parse_profile_meta("no stats here") == {
        "followers": 0, "following": 0, "posts": 0}


# ── captions ────────────────────────────────────────────────────────────────

def test_compose_caption_basic():
    r = im.compose_caption("Sunset vibes", "travel, sunset")
    assert r["caption"] == "Sunset vibes\n\n#travel #sunset"
    assert r["hashtags"] == ["travel", "sunset"]
    assert not r["truncated"]


def test_compose_caption_dedupes_and_strips_hash():
    r = im.compose_caption("hi", ["#Travel", "travel", "TRAVEL", "#food"])
    assert r["hashtags"] == ["travel", "food"]


def test_compose_caption_hashtag_cap():
    r = im.compose_caption("hi", [f"tag{i}" for i in range(40)])
    assert len(r["hashtags"]) == im.HASHTAG_MAX
    assert any("30 hashtags" in w for w in r["warnings"])


def test_compose_caption_mentions():
    r = im.compose_caption("shot by", None, "@alice bob")
    assert "@alice" in r["caption"] and "@bob" in r["caption"]
    assert r["mentions"] == ["alice", "bob"]


def test_compose_caption_invalid_mention_warns():
    r = im.compose_caption("x", None, ["ok", "bad name!"])
    assert r["mentions"] == ["ok"]
    assert any("invalid mentions" in w for w in r["warnings"])


def test_compose_caption_truncates_to_limit():
    r = im.compose_caption("a" * 3000)
    assert r["length"] <= im.CAPTION_MAX
    assert r["truncated"]
    assert r["warnings"]


def test_compose_caption_truncation_keeps_hashtags():
    r = im.compose_caption("b" * 3000, "keepme")
    assert r["length"] <= im.CAPTION_MAX
    assert "#keepme" in r["caption"]


def test_compose_caption_empty():
    assert im.compose_caption()["caption"] == ""


# ── media validation ────────────────────────────────────────────────────────

def _img(tmp_path, name="a.jpg", size=1024):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return p


def test_validate_media_single_photo(tmp_path):
    r = im.validate_media([_img(tmp_path)], "post")
    assert r["ok"] and r["kind"] == "post" and len(r["files"]) == 1


def test_validate_media_auto_carousel(tmp_path):
    files = [_img(tmp_path, f"{i}.jpg") for i in range(3)]
    r = im.validate_media(files, "post")
    assert r["ok"] and r["kind"] == "carousel"


def test_validate_media_auto_reel(tmp_path):
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"x" * 10)
    r = im.validate_media([v], "post")
    assert r["ok"] and r["kind"] == "reel"


def test_validate_media_missing_file(tmp_path):
    r = im.validate_media([tmp_path / "nope.jpg"])
    assert not r["ok"] and "Not found" in r["errors"][0]


def test_validate_media_bad_extension(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"x")
    r = im.validate_media([p])
    assert not r["ok"] and "Unsupported type" in r["errors"][0]


def test_validate_media_directory_rejected(tmp_path):
    r = im.validate_media([tmp_path])
    assert not r["ok"] and "Not a file" in r["errors"][0]


def test_validate_media_empty():
    r = im.validate_media([])
    assert not r["ok"] and "No media file" in r["errors"][0]


def test_validate_media_carousel_needs_two(tmp_path):
    r = im.validate_media([_img(tmp_path)], "carousel")
    assert not r["ok"] and "at least 2" in r["errors"][0]


def test_validate_media_carousel_max(tmp_path):
    files = [_img(tmp_path, f"{i}.jpg") for i in range(11)]
    r = im.validate_media(files, "carousel")
    assert not r["ok"] and "at most 10" in r["errors"][0]


def test_validate_media_reel_needs_video(tmp_path):
    r = im.validate_media([_img(tmp_path)], "reel")
    assert not r["ok"] and "needs a video" in r["errors"][0]


def test_validate_media_reel_single_only(tmp_path):
    vids = []
    for i in range(2):
        v = tmp_path / f"v{i}.mp4"
        v.write_bytes(b"x")
        vids.append(v)
    r = im.validate_media(vids, "reel")
    assert not r["ok"] and "exactly one video" in r["errors"][0]


def test_validate_media_story_single(tmp_path):
    r = im.validate_media([_img(tmp_path, "s.jpg")], "story")
    assert r["ok"] and r["kind"] == "story"


def test_validate_media_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "IMAGE_MAX_MB", 0)
    r = im.validate_media([_img(tmp_path, size=2048)])
    assert not r["ok"] and "limit" in r["errors"][0]


def test_validate_media_mixed_carousel_warns(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    r = im.validate_media([_img(tmp_path), v], "carousel")
    assert r["ok"] and r["warnings"]


# ── activity ledger ─────────────────────────────────────────────────────────

def test_ledger_unlisted_kind_unlimited(tmp_path):
    led = im.ActivityLedger(tmp_path / "s.json")
    assert led.check("whatever", now=1000.0) == (True, "")


def test_ledger_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setitem(im.DAILY_CAPS, "follow", 2)
    led = im.ActivityLedger(tmp_path / "s.json")
    now = 1_700_000_000.0
    led.record("follow", now)
    led.record("follow", now + 100)
    ok, reason = led.check("follow", now + 200)
    assert not ok and "Daily follow limit" in reason


def test_ledger_min_interval(tmp_path):
    led = im.ActivityLedger(tmp_path / "s.json")
    now = 1_700_000_000.0
    led.record("dm", now)
    ok, reason = led.check("dm", now + 1)
    assert not ok and "Slow down" in reason
    assert led.check("dm", now + im.MIN_INTERVAL_S["dm"] + 1)[0]


def test_ledger_persists(tmp_path):
    p = tmp_path / "s.json"
    im.ActivityLedger(p).record("like", 1_700_000_000.0)
    again = im.ActivityLedger(p)
    assert again.count_today("like", 1_700_000_000.0) == 1


def test_ledger_new_day_resets(tmp_path):
    led = im.ActivityLedger(tmp_path / "s.json")
    now = 1_700_000_000.0
    led.record("like", now)
    assert led.count_today("like", now + 86400 * 2) == 0


def test_ledger_corrupt_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    led = im.ActivityLedger(p)
    assert led.counts_today() == {}


def test_ledger_summary(tmp_path):
    led = im.ActivityLedger(tmp_path / "s.json")
    assert "No Instagram actions" in led.summary()
    led.record("post", 1_700_000_000.0)
    assert "post: 1/10" in led.summary(1_700_000_000.0)


# ── schedule queue ──────────────────────────────────────────────────────────

def test_queue_add_and_render(tmp_path):
    q = im.PostQueue(tmp_path / "q.json")
    res = q.add([_img(tmp_path)], "caption", when=2000.0, now=1000.0)
    assert res["ok"]
    assert "Scheduled posts (1)" in q.render()
    assert res["item"]["status"] == "pending"


def test_queue_add_rejects_bad_media(tmp_path):
    q = im.PostQueue(tmp_path / "q.json")
    assert not q.add([tmp_path / "missing.jpg"], now=1000.0)["ok"]


def test_queue_due(tmp_path):
    q = im.PostQueue(tmp_path / "q.json")
    q.add([_img(tmp_path)], when=1500.0, now=1000.0)
    assert q.due(now=1200.0) == []
    assert len(q.due(now=1600.0)) == 1


def test_queue_cancel(tmp_path):
    q = im.PostQueue(tmp_path / "q.json")
    item = q.add([_img(tmp_path)], now=1000.0)["item"]
    assert q.cancel(item["id"])
    assert q.list("pending") == []
    assert not q.cancel(item["id"])


def test_queue_mark_done_excludes_from_due(tmp_path):
    q = im.PostQueue(tmp_path / "q.json")
    item = q.add([_img(tmp_path)], when=1000.0, now=900.0)["item"]
    q.mark(item["id"], "done")
    assert q.due(now=2000.0) == []


def test_queue_persists(tmp_path):
    p = tmp_path / "q.json"
    im.PostQueue(p).add([_img(tmp_path)], now=1000.0)
    assert len(im.PostQueue(p).list()) == 1


def test_queue_empty_render(tmp_path):
    assert "No scheduled" in im.PostQueue(tmp_path / "q.json").render()


def test_queue_corrupt(tmp_path):
    p = tmp_path / "q.json"
    p.write_text("nonsense")
    assert im.PostQueue(p).list() == []


# ── report ──────────────────────────────────────────────────────────────────

def test_build_report(tmp_path):
    led = im.ActivityLedger(tmp_path / "s.json")
    led.record("post", 1_700_000_000.0)
    q = im.PostQueue(tmp_path / "q.json")
    q.add([_img(tmp_path)], when=1_700_000_500.0, now=1_700_000_000.0)
    text = im.build_report({"username": "me", "followers": 1200, "following": 300,
                            "posts": 42}, led, q, now=1_700_000_100.0)
    assert "# Instagram report" in text
    assert "@me" in text and "1,200" in text
    assert "post: 1 / 10" in text
    assert "Nothing scheduled" not in text


def test_build_report_empty(tmp_path):
    text = im.build_report(now=1_700_000_000.0)
    assert "No actions recorded today" in text
    assert "Nothing scheduled" in text


# ── confirmation gate ───────────────────────────────────────────────────────

def test_confirm_required():
    msg = im.require_confirm({}, "post")
    assert im.CONFIRM_TEXT in msg


def test_confirm_accepted():
    assert im.require_confirm({"confirm": im.CONFIRM_TEXT}, "post") is None


def test_dry_run_bypasses():
    assert "Dry run" in im.require_confirm({"dry_run": True}, "post")


def test_wrong_confirm_rejected():
    assert im.require_confirm({"confirm": "yes"}, "dm") is not None


# ── browser primitives ──────────────────────────────────────────────────────

def test_first_finds_visible(no_sleep):
    el = FakeElement()
    d = FakeDriver({"input[name='queryBox']": [el]})
    assert im._first(d, ["nope", "input[name='queryBox']"], timeout=0) is el


def test_first_returns_none(no_sleep):
    assert im._first(FakeDriver(), ["x"], timeout=0) is None


def test_click_text(no_sleep):
    btn = FakeElement(label="Follow")
    d = FakeDriver(buttons={"Follow": btn})
    assert im._click_text(d, ["Follow"]) is True
    assert btn.clicks == 1


def test_click_text_missing(no_sleep):
    assert im._click_text(FakeDriver(), ["Nope"]) is False


def test_type_box_returns_same_element(no_sleep):
    boxes = [FakeElement(), FakeElement()]
    d = FakeDriver({"div[contenteditable='true'][role='textbox']": boxes})
    got = im._type_box(d, "hello")
    assert got is boxes[-1]
    assert got.keys == ["hello"] and got.clicks == 1


def test_type_box_none(no_sleep):
    assert im._type_box(FakeDriver(), "x") is None


def test_upload(no_sleep, tmp_path):
    inp = FakeElement()
    d = FakeDriver({"input[type='file']": [inp]})
    f = _img(tmp_path)
    assert im._upload(d, str(f)) is True
    assert inp.keys and inp.keys[0].endswith("a.jpg")


def test_upload_no_input(no_sleep, tmp_path):
    assert im._upload(FakeDriver(), str(_img(tmp_path))) is False


def test_goto_normalizes_url(no_sleep):
    d = FakeDriver()
    im._goto(d, "/alice/")
    assert d.urls[-1] == im.BASE_URL + "/alice/"


# ── browser operations ──────────────────────────────────────────────────────

def _dm_driver():
    box = FakeElement()
    search = FakeElement()
    result = FakeElement(text="alice")
    d = FakeDriver(
        {"input[name='queryBox']": [search],
         "div[contenteditable='true'][role='textbox']": [box]},
        {"Chat": FakeElement(label="Chat")},
    )
    d.find_elements_orig = d.find_elements

    def find(by, value):
        if by == im.XPATH and "contains(text()" in value:
            return [result]
        return d.find_elements_orig(by, value)

    d.find_elements = find
    return d, box


def test_op_dm_send(no_sleep):
    d, box = _dm_driver()
    out = im.op_dm_send(d, "@alice", "hey there")
    assert out.startswith("✉️") and "alice" in out
    assert "hey there" in box.keys and im.ENTER in box.keys


def test_op_dm_send_invalid_user(no_sleep):
    assert "Invalid" in im.op_dm_send(FakeDriver(), "bad name", "hi")


def test_op_dm_send_no_thread(no_sleep):
    assert "Could not open" in im.op_dm_send(FakeDriver(), "alice", "hi")


def test_op_dm_image(no_sleep, tmp_path):
    d, _ = _dm_driver()
    inp = FakeElement()
    d.css_map["input[type='file']"] = [inp]
    d.buttons["Send"] = FakeElement(label="Send")
    out = im.op_dm_image(d, "alice", str(_img(tmp_path)))
    assert out.startswith("🖼️") and inp.keys


def test_op_dm_image_rejects_video(no_sleep, tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    d, _ = _dm_driver()
    assert "must be an image" in im.op_dm_image(d, "alice", str(v))


def test_op_inbox(no_sleep):
    t = FakeElement(text="alice  hey!", attrs={"href": im.BASE_URL + "/direct/t/1"})
    d = FakeDriver({"a[href^='/direct/t/']": [t]})
    out = im.op_inbox(d)
    assert "Inbox (1 threads)" in out and "hey!" in out


def test_op_inbox_empty(no_sleep):
    assert "No DM threads" in im.op_inbox(FakeDriver())


def test_op_dm_read(no_sleep):
    msgs = [FakeElement(text="hello"), FakeElement(text="how are you")]
    d = FakeDriver({"div[role='row']": msgs})
    out = im.op_dm_read(d, url=im.BASE_URL + "/direct/t/1")
    assert "hello" in out and "how are you" in out


def test_op_follow(no_sleep):
    btn = FakeElement(label="Follow")
    d = FakeDriver(buttons={"Follow": btn})
    assert im.op_follow(d, "@alice").startswith("➕")
    assert btn.clicks == 1


def test_op_unfollow(no_sleep):
    d = FakeDriver(buttons={"Following": FakeElement(), "Unfollow": FakeElement()})
    assert im.op_follow(d, "alice", unfollow=True).startswith("➖")


def test_op_follow_invalid(no_sleep):
    assert "Invalid" in im.op_follow(FakeDriver(), "bad name")


def test_op_follow_already(no_sleep):
    assert "Already following" in im.op_follow(FakeDriver(), "alice")


def test_op_engage_like(no_sleep):
    svg = FakeElement()
    d = FakeDriver({"svg[aria-label='Like']": [svg]})
    out = im.op_engage(d, im.BASE_URL + "/p/abc/", "like")
    assert "done" in out and svg.clicks == 1


def test_op_engage_missing(no_sleep):
    assert "Could not find" in im.op_engage(FakeDriver(), "https://x/p/1", "like")


def test_op_engage_no_url(no_sleep):
    assert "Provide the post URL" in im.op_engage(FakeDriver(), "", "like")


def test_op_comment(no_sleep):
    box = FakeElement()
    d = FakeDriver({"textarea[aria-label='Add a comment…']": [box]})
    out = im.op_comment(d, "https://x/p/1", "nice shot")
    assert out.startswith("💬")
    assert "nice shot" in box.keys and im.ENTER in box.keys


def test_op_comment_no_box(no_sleep):
    assert "Could not find the comment box" in im.op_comment(FakeDriver(), "u", "t")


def test_op_profile(no_sleep):
    meta = FakeElement(attrs={"content": "1,234 Followers, 567 Following, 89 Posts"})
    title = FakeElement(attrs={"content": "Alice (@alice)"})
    d = FakeDriver({"meta[name='description']": [meta],
                    "meta[property='og:title']": [title]})
    res = im.op_profile(d, "@alice")
    assert res["ok"] and res["followers"] == 1234 and res["posts"] == 89
    assert res["title"] == "Alice (@alice)"


def test_op_profile_invalid(no_sleep):
    assert not im.op_profile(FakeDriver(), "bad name")["ok"]


def test_op_edit_bio(no_sleep):
    box = FakeElement()
    d = FakeDriver({"textarea#pepBio": [box]}, {"Submit": FakeElement()})
    assert "Bio updated" in im.op_edit_bio(d, "new bio")
    assert box.cleared == 1 and box.keys == ["new bio"]


def test_op_edit_bio_no_field(no_sleep):
    assert "Could not find the bio" in im.op_edit_bio(FakeDriver(), "x")


def test_op_set_avatar(no_sleep, tmp_path):
    inp = FakeElement()
    d = FakeDriver({"input[type='file']": [inp]})
    assert "Profile photo updated" in im.op_set_avatar(d, str(_img(tmp_path)))


def test_op_my_posts(no_sleep):
    a = FakeElement(attrs={"href": im.BASE_URL + "/p/abc/"})
    d = FakeDriver({"a[href*='/p/'], a[href*='/reel/']": [a]})
    out = im.op_my_posts(d, "alice")
    assert "/p/abc/" in out


def test_op_my_posts_empty(no_sleep):
    assert "No posts found" in im.op_my_posts(FakeDriver(), "alice")


def test_op_requests(no_sleep):
    d = FakeDriver(buttons={"Confirm": FakeElement()})
    assert "Accepted" in im.op_requests(d, accept=True)


def test_op_requests_decline(no_sleep):
    d = FakeDriver(buttons={"Delete": FakeElement()})
    assert "Declined" in im.op_requests(d, accept=False)


def test_op_post_photo(no_sleep, tmp_path):
    inp = FakeElement()
    d = FakeDriver({"input[type='file']": [inp],
                    "svg[aria-label='New post']": [FakeElement()]},
                   {"Next": FakeElement(), "Share": FakeElement()})
    out = im.op_post(d, [str(_img(tmp_path))], "my caption", "post")
    assert out.startswith("📸") and inp.keys


def test_op_post_bad_media(no_sleep, tmp_path):
    assert "Media problem" in im.op_post(FakeDriver(), [tmp_path / "x.jpg"])


def test_op_post_carousel_uploads_all(no_sleep, tmp_path):
    inp = FakeElement()
    d = FakeDriver({"input[type='file']": [inp],
                    "svg[aria-label='Create']": [FakeElement()]},
                   {"Next": FakeElement(), "Share": FakeElement(),
                    "Select multiple": FakeElement()})
    files = [str(_img(tmp_path, f"{i}.jpg")) for i in range(3)]
    out = im.op_post(d, files, "album", "carousel")
    assert "carousel" in out and len(inp.keys) == 3


def test_op_post_story(no_sleep, tmp_path):
    d = FakeDriver({"input[type='file']": [FakeElement()]},
                   {"Add to story": FakeElement()})
    assert im.op_post(d, [str(_img(tmp_path))], "", "story").startswith("📖")


def test_op_post_reel(no_sleep, tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    d = FakeDriver({"input[type='file']": [FakeElement()]},
                   {"Next": FakeElement(), "Share": FakeElement()})
    assert im.op_post(d, [str(v)], "reel time", "reel").startswith("🎬")


def test_op_follow_list(no_sleep):
    links = [FakeElement(attrs={"href": im.BASE_URL + "/bob/"}),
             FakeElement(attrs={"href": im.BASE_URL + "/carol/"})]
    d = FakeDriver({"div[role='dialog'] a[href^='/']": links},
                   {"Followers": FakeElement()})
    res = im.op_follow_list(d, "alice", "followers", scrolls=1)
    assert res["ok"] and res["handles"] == ["bob", "carol"]


def test_op_follow_list_invalid(no_sleep):
    assert not im.op_follow_list(FakeDriver(), "bad name")["ok"]


# ── dispatcher ──────────────────────────────────────────────────────────────

def test_dispatch_help():
    out = im.instagram_manager({"action": "help"})
    assert "Instagram Manager" in out and "dm_image" in out


def test_dispatch_unknown(session, tmp_path):
    session(FakeDriver(), tmp_path)
    assert "Unknown Instagram action" in im.instagram_manager({"action": "nope"})


def test_dispatch_status(session, tmp_path):
    session(FakeDriver(), tmp_path)
    assert "connected" in im.instagram_manager({"action": "status"})


def test_dispatch_activity_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "STATE_PATH", tmp_path / "s.json")
    assert "No Instagram actions" in im.instagram_manager({"action": "activity"})


def test_dispatch_mutating_needs_confirm(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "post", "media": "x.jpg"})
    assert im.CONFIRM_TEXT in out


def test_dispatch_alias_cannot_bypass_confirm(session, tmp_path):
    session(FakeDriver(), tmp_path)
    for alias in ("photo", "upload", "video", "message", "dm_photo", "post_story"):
        out = im.instagram_manager({"action": alias})
        assert im.CONFIRM_TEXT in out, alias


def test_dispatch_dry_run(session, tmp_path):
    session(FakeDriver(), tmp_path)
    assert "Dry run" in im.instagram_manager({"action": "dm", "dry_run": True})


def test_dispatch_dm_records_ledger(session, tmp_path):
    d, box = _dm_driver()
    session(d, tmp_path)
    out = im.instagram_manager({"action": "dm", "username": "alice",
                                "message": "hi", "confirm": im.CONFIRM_TEXT})
    assert out.startswith("✉️")
    assert im.ActivityLedger(tmp_path / "state.json").count_today("dm") == 1


def test_dispatch_dm_rate_limited(session, tmp_path):
    d, _ = _dm_driver()
    session(d, tmp_path)
    p = {"action": "dm", "username": "alice", "message": "hi",
         "confirm": im.CONFIRM_TEXT}
    im.instagram_manager(p)
    again = im.instagram_manager(p)
    assert "Slow down" in again


def test_dispatch_follow(session, tmp_path):
    d = FakeDriver(buttons={"Follow": FakeElement()})
    session(d, tmp_path)
    out = im.instagram_manager({"action": "follow", "username": "alice",
                                "confirm": im.CONFIRM_TEXT})
    assert out.startswith("➕")


def test_dispatch_unfollow_records_unfollow(session, tmp_path):
    d = FakeDriver(buttons={"Following": FakeElement(), "Unfollow": FakeElement()})
    session(d, tmp_path)
    out = im.instagram_manager({"action": "unfollow", "username": "alice",
                                "confirm": im.CONFIRM_TEXT})
    assert out.startswith("➖")
    led = im.ActivityLedger(tmp_path / "state.json")
    assert led.count_today("unfollow") == 1
    assert led.count_today("follow") == 0


def test_dispatch_batch_cap(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "follow_many",
                                "usernames": [f"user{i}" for i in range(11)],
                                "confirm": im.CONFIRM_TEXT})
    assert "cap batches at 10" in out


def test_dispatch_dm_many_cap(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "dm_many",
                                "usernames": [f"user{i}" for i in range(11)],
                                "message": "hi", "confirm": im.CONFIRM_TEXT})
    assert "cap batches at 10" in out


def test_dispatch_follow_many_needs_users(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "follow_many",
                                "confirm": im.CONFIRM_TEXT})
    assert "Provide usernames" in out


def test_dispatch_profile(session, tmp_path):
    meta = FakeElement(attrs={"content": "10 Followers, 20 Following, 3 Posts"})
    d = FakeDriver({"meta[name='description']": [meta]})
    session(d, tmp_path)
    out = im.instagram_manager({"action": "profile", "username": "alice"})
    assert "Followers: 10" in out and "Posts:     3" in out


def test_dispatch_schedule_and_queue(session, tmp_path):
    session(FakeDriver(), tmp_path)
    img = _img(tmp_path)
    out = im.instagram_manager({"action": "schedule", "media": str(img),
                                "caption": "later", "when": 1_700_000_000})
    assert "Scheduled [" in out
    assert "Scheduled posts (1)" in im.instagram_manager({"action": "queue"})


def test_dispatch_schedule_bad_when(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "schedule", "media": str(_img(tmp_path)),
                                "when": "tomorrow"})
    assert "Unix timestamp" in out


def test_dispatch_unschedule(session, tmp_path):
    session(FakeDriver(), tmp_path)
    img = str(_img(tmp_path))
    im.instagram_manager({"action": "schedule", "media": img, "when": 1_700_000_000})
    item = im.PostQueue(tmp_path / "queue.json").list()[0]
    assert "Cancelled" in im.instagram_manager({"action": "unschedule", "id": item["id"]})


def test_dispatch_unschedule_no_id(session, tmp_path):
    session(FakeDriver(), tmp_path)
    assert "Which scheduled post" in im.instagram_manager({"action": "unschedule"})


def test_dispatch_run_due_nothing(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "run_due", "confirm": im.CONFIRM_TEXT})
    assert "Nothing is due" in out


def test_dispatch_not_following_back_pure(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "not_following_back",
                                "followers": ["a"], "following": ["a", "b"]})
    assert "@b" in out and "@a" not in out


def test_dispatch_mutuals_none(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "mutuals",
                                "followers": ["a"], "following": ["b"]})
    assert "none found" in out


def test_dispatch_session_error(monkeypatch, tmp_path):
    monkeypatch.setattr(im, "_session", lambda p, player=None: (None, "no browser"))
    monkeypatch.setattr(im, "STATE_PATH", tmp_path / "s.json")
    assert im.instagram_manager({"action": "inbox"}) == "no browser"


def test_dispatch_quits_driver(session, tmp_path):
    d = session(FakeDriver(), tmp_path)
    im.instagram_manager({"action": "status"})
    assert d.quit_called == 1


def test_dispatch_keep_open(session, tmp_path):
    d = session(FakeDriver(), tmp_path)
    im.instagram_manager({"action": "status", "keep_open": True})
    assert d.quit_called == 0


def test_dispatch_comment_records(session, tmp_path):
    box = FakeElement()
    d = FakeDriver({"textarea[aria-label='Add a comment…']": [box]})
    session(d, tmp_path)
    out = im.instagram_manager({"action": "comment", "url": "https://x/p/1",
                                "text": "great", "confirm": im.CONFIRM_TEXT})
    assert out.startswith("💬")
    assert im.ActivityLedger(tmp_path / "state.json").count_today("comment") == 1


def test_dispatch_edit_bio_needs_text(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "edit_bio", "confirm": im.CONFIRM_TEXT})
    assert "What should the new bio" in out


def test_dispatch_report(session, tmp_path):
    session(FakeDriver(), tmp_path)
    out = im.instagram_manager({"action": "report"})
    assert "# Instagram report" in out
