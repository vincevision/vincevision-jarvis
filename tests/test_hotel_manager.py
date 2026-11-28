"""Offline tests for the hotel meta-search (actions/hotel_manager.py).

No network and no browser: `_browser` is faked, the clock is virtual, and all
state lives in tmp_path. Covers URL building, price/rating parsing, ranking,
watches, rate limits, visibility narration, and crash-proofing.
"""

import json
from datetime import datetime

import pytest

from actions import hotel_manager as hm


class FakeClock:
    """Virtual time — sleep() advances it, so rate-limit tests stay instant."""

    def __init__(self, start=1_800_000_000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += float(seconds)


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(hm, "time", c)
    return c


@pytest.fixture
def store(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(hm, "WATCH_PATH", tmp_path / "watches.json")
    monkeypatch.setattr(hm, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(hm, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(hm, "CONFIG_PATH", tmp_path / "hotels.json")
    monkeypatch.setattr(hm, "SITE_DELAY_S", 0)
    monkeypatch.setenv("JARVIS_PACE", "0")
    monkeypatch.setenv("JARVIS_SHOW_ME", "1")
    return tmp_path


PAGE = """Rove Downtown Dubai
4-star hotel
8.6
1,204 reviews
USD 120 per night

Premier Inn Dubai Al Jaddaf
3-star hotel
8.1
860 reviews
USD 78 per night

Atlantis The Palm
5-star hotel
9.2
15,400 reviews
USD 450 per night
"""


@pytest.fixture
def browser(monkeypatch, store):
    calls = []

    def fake(params, player=None):
        calls.append(params)
        if params.get("action") == "get_text":
            return PAGE
        return "opened"
    monkeypatch.setattr(hm, "_browser", fake)
    return calls


@pytest.fixture
def search():
    return hm.build_search({"city": "Dubai", "checkin": "2026-12-15",
                            "nights": 5, "guests": 2, "currency": "USD"})


@pytest.fixture
def narrator(store):
    from core.visible import Narrator
    return Narrator(config={"show_me": True, "pace": 0}, sleeper=lambda s: None)


# ── dates ──────────────────────────────────────────────────────────────────

def test_parse_date_iso():
    assert hm.parse_date("2026-12-15") == "2026-12-15"


def test_parse_date_relative():
    today = datetime(2026, 11, 28)
    assert hm.parse_date("tomorrow", today) == "2026-11-29"


def test_parse_date_empty():
    assert hm.parse_date("") == ""
    assert hm.parse_date(None) == ""


def test_nights_between():
    assert hm.nights_between("2026-12-15", "2026-12-20") == 5


def test_nights_between_bad_input():
    assert hm.nights_between("", "") == 0
    assert hm.nights_between("nope", "2026-12-20") == 0


def test_date_grid_size():
    assert len(hm.date_grid("2026-12-15", 3)) == 7


def test_date_grid_clamped():
    assert len(hm.date_grid("2026-12-15", 99)) == 2 * hm.MAX_FLEX_DAYS + 1


def test_date_grid_bad_date():
    assert hm.date_grid("nonsense", 3) == []


# ── build_search validation ────────────────────────────────────────────────

def test_build_search_ok(search):
    assert search["ok"] is True
    assert search["checkout"] == "2026-12-20" and search["nights"] == 5


def test_build_search_needs_city():
    s = hm.build_search({"checkin": "2026-12-15"})
    assert not s["ok"] and any("city" in e.lower() for e in s["errors"])


def test_build_search_needs_date():
    assert not hm.build_search({"city": "Dubai"})["ok"]


def test_build_search_default_one_night():
    s = hm.build_search({"city": "Dubai", "checkin": "2026-12-15"})
    assert s["nights"] == 1 and s["checkout"] == "2026-12-16"


def test_build_search_explicit_checkout():
    s = hm.build_search({"city": "Dubai", "checkin": "2026-12-15", "checkout": "2026-12-18"})
    assert s["nights"] == 3


def test_build_search_checkout_before_checkin():
    s = hm.build_search({"city": "Dubai", "checkin": "2026-12-15", "checkout": "2026-12-10"})
    assert not s["ok"]


def test_build_search_destination_alias():
    assert hm.build_search({"destination": "Dubai", "checkin": "2026-12-15"})["city"] == "Dubai"


def test_build_search_date_alias():
    assert hm.build_search({"city": "Dubai", "date": "2026-12-15"})["checkin"] == "2026-12-15"


@pytest.mark.parametrize("guests", [0, 17, -1])
def test_build_search_bad_guests(guests):
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "guests": guests})["ok"]


def test_build_search_non_numeric_guests():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "guests": "two"})["ok"]


@pytest.mark.parametrize("rooms", [0, 9])
def test_build_search_bad_rooms(rooms):
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "rooms": rooms})["ok"]


def test_build_search_negative_nights():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "nights": -2})["ok"]


def test_build_search_non_numeric_nights():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "nights": "five"})["ok"]


def test_build_search_bad_max_price():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "max_price": "cheap"})["ok"]


def test_build_search_negative_max_price():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "max_price": -5})["ok"]


def test_build_search_budget_alias():
    assert hm.build_search({"city": "D", "checkin": "2026-12-15", "budget": 150})["max_price"] == 150


def test_build_search_rating_out_of_range():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "min_rating": 11})["ok"]


def test_build_search_bad_rating():
    assert not hm.build_search({"city": "D", "checkin": "2026-12-15", "min_rating": "great"})["ok"]


def test_build_search_currency_fallback():
    assert hm.build_search({"city": "D", "checkin": "2026-12-15", "currency": "dollars"})["currency"] == "USD"


def test_build_search_currency_upper():
    assert hm.build_search({"city": "D", "checkin": "2026-12-15", "currency": "eur"})["currency"] == "EUR"


# ── site list ──────────────────────────────────────────────────────────────

def test_site_list_default_is_all():
    assert hm._site_list(None) == list(hm.SITES)
    assert hm._site_list("all") == list(hm.SITES)


def test_site_list_csv():
    assert hm._site_list("booking,google") == ["booking", "google"]


def test_site_list_aliases():
    assert hm._site_list("booking.com,hotels.com") == ["booking", "hotels"]


def test_site_list_dedupes():
    assert hm._site_list("booking,booking") == ["booking"]


def test_site_list_drops_unknown():
    assert hm._site_list("booking,trivago,zzz") == ["booking"]


def test_site_list_capped():
    assert len(hm._site_list(",".join(hm.SITES))) <= hm.MAX_SITES


def test_site_list_empty_string():
    assert hm._site_list("") == list(hm.SITES)


# ── deep links ─────────────────────────────────────────────────────────────

def test_all_sites_have_urls(search):
    urls = hm.all_urls(search)
    assert set(urls) == set(hm.SITES)
    assert all(u.startswith("https://") for u in urls.values())


def test_booking_url_params(search):
    url = hm.build_url("booking", search)
    assert "booking.com/searchresults" in url
    assert "checkin=2026-12-15" in url and "checkout=2026-12-20" in url
    assert "group_adults=2" in url and "selected_currency=USD" in url


def test_booking_url_price_filter(search):
    s = dict(search, max_price=150)
    assert "nflt=price" in hm.build_url("booking", s)


def test_airbnb_url(search):
    url = hm.build_url("airbnb", search)
    assert "airbnb.com/s/Dubai/homes" in url and "adults=2" in url


def test_airbnb_price_cap(search):
    assert "price_max=150" in hm.build_url("airbnb", dict(search, max_price=150))


def test_expedia_url(search):
    url = hm.build_url("expedia", search)
    assert "expedia.com/Hotel-Search" in url and "startDate=2026-12-15" in url


def test_hotels_com_url(search):
    assert "hotels.com/Hotel-Search" in hm.build_url("hotels", search)


def test_expedia_rating_filter(search):
    assert "guestRating=8" in hm.build_url("expedia", dict(search, min_rating=8.5))


def test_agoda_url_length_of_stay(search):
    assert "los=5" in hm.build_url("agoda", search)


def test_kayak_url(search):
    url = hm.build_url("kayak", search)
    assert "kayak.com/hotels/Dubai/2026-12-15/2026-12-20/2adults" in url


def test_google_url(search):
    url = hm.build_url("google", search)
    assert "google.com/travel/hotels" in url and "curr=USD" in url


def test_unknown_site_url_empty(search):
    assert hm.build_url("trivago", search) == ""


def test_city_is_url_encoded(search):
    s = dict(search, city="New York")
    assert "New+York" in hm.build_url("booking", s)


def test_urls_are_deterministic(search):
    assert hm.all_urls(search) == hm.all_urls(search)


# ── parsing ────────────────────────────────────────────────────────────────

def test_parse_prices_symbols():
    assert hm.parse_prices("$120 and €95") == [120.0, 95.0]


def test_parse_prices_thousands():
    assert hm.parse_prices("USD 1,250") == [1250.0]


def test_parse_prices_iso_codes():
    assert hm.parse_prices("KES 8500") == [8500.0]


def test_parse_prices_no_phantom_from_hours():
    # 'R' (ZAR) must not match the 'r' inside '8 hr'
    assert hm.parse_prices("8 hr 30 min") == []


def test_parse_prices_empty():
    assert hm.parse_prices("") == []
    assert hm.parse_prices(None) == []


def test_parse_rating_ten_scale():
    assert hm.parse_rating("8.6") == 8.6


def test_parse_rating_five_scale_doubled():
    assert hm.parse_rating("4.5/5") == 9.0


def test_parse_rating_explicit_ten():
    assert hm.parse_rating("8.6/10") == 8.6


def test_parse_rating_none():
    assert hm.parse_rating("no score here") == 0.0
    assert hm.parse_rating("") == 0.0


def test_parse_reviews():
    assert hm.parse_reviews("1,204 reviews") == 1204
    assert hm.parse_reviews("860 guest reviews") == 860


def test_parse_reviews_none():
    assert hm.parse_reviews("nothing") == 0


def test_parse_stars():
    assert hm.parse_stars("4-star hotel") == 4
    assert hm.parse_stars("5 star") == 5


def test_parse_stars_none():
    assert hm.parse_stars("boutique") == 0


def test_extract_stays_finds_all():
    stays = hm.extract_stays(PAGE, "booking", "USD")
    assert len(stays) == 3
    assert [s["price"] for s in stays] == [120.0, 78.0, 450.0]


def test_extract_stays_names():
    stays = hm.extract_stays(PAGE, "booking")
    assert "Rove Downtown" in stays[0]["name"]


def test_extract_stays_ratings_not_bleeding():
    stays = hm.extract_stays(PAGE, "booking")
    assert stays[0]["rating"] == 8.6
    assert stays[1]["rating"] == 8.1
    assert stays[2]["rating"] == 9.2


def test_extract_stays_reviews():
    stays = hm.extract_stays(PAGE, "booking")
    assert stays[0]["reviews"] == 1204


def test_extract_stays_stars():
    stays = hm.extract_stays(PAGE, "booking")
    assert stays[0]["stars"] == 4 and stays[2]["stars"] == 5


def test_extract_stays_site_and_currency():
    stays = hm.extract_stays(PAGE, "agoda", "EUR")
    assert all(s["site"] == "agoda" and s["currency"] == "EUR" for s in stays)


def test_extract_stays_empty():
    assert hm.extract_stays("", "booking") == []
    assert hm.extract_stays(None) == []


def test_extract_stays_limit():
    assert len(hm.extract_stays(PAGE, "booking", limit=2)) == 2


def test_extract_stays_dedupes():
    assert len(hm.extract_stays(PAGE + PAGE, "booking")) == 3


def test_extract_stays_no_prices():
    assert hm.extract_stays("Just text\nNo numbers", "booking") == []


# ── ranking ────────────────────────────────────────────────────────────────

def test_score_stay_price_dominates():
    cheap = {"price": 80, "rating": 8.0, "reviews": 500}
    pricey = {"price": 400, "rating": 9.0, "reviews": 500}
    assert hm.score_stay(cheap) < hm.score_stay(pricey)


def test_score_stay_rating_bonus():
    good = {"price": 100, "rating": 9.0, "reviews": 500}
    poor = {"price": 100, "rating": 5.0, "reviews": 500}
    assert hm.score_stay(good) < hm.score_stay(poor)


def test_score_stay_no_reviews_penalty():
    known = {"price": 100, "rating": 8.0, "reviews": 500}
    unknown = {"price": 100, "rating": 8.0, "reviews": 0}
    assert hm.score_stay(unknown) > hm.score_stay(known)


def test_score_stay_few_reviews_penalty():
    many = {"price": 100, "rating": 8.0, "reviews": 500}
    few = {"price": 100, "rating": 8.0, "reviews": 5}
    assert hm.score_stay(few) > hm.score_stay(many)


def test_score_stay_star_penalty():
    st = {"price": 100, "rating": 8.0, "reviews": 500, "stars": 2}
    assert hm.score_stay(st, {"min_stars": 4}) > hm.score_stay(st)


def test_score_stay_missing_fields():
    assert hm.score_stay({}) >= 0


def test_rank_stays_sorted_by_score():
    stays = hm.extract_stays(PAGE, "booking")
    ranked = hm.rank_stays(stays)
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores)


def test_rank_stays_max_price_filter():
    ranked = hm.rank_stays(hm.extract_stays(PAGE, "booking"), max_price=150)
    assert all(r["price"] <= 150 for r in ranked)
    assert len(ranked) == 2


def test_rank_stays_min_rating_filter():
    ranked = hm.rank_stays(hm.extract_stays(PAGE, "booking"), min_rating=9.0)
    assert len(ranked) == 1 and ranked[0]["price"] == 450.0


def test_rank_stays_empty():
    assert hm.rank_stays([]) == []
    assert hm.rank_stays(None) == []


def test_rank_stays_does_not_mutate():
    stays = hm.extract_stays(PAGE, "booking")
    hm.rank_stays(stays)
    assert "score" not in stays[0]


def test_cheapest_by_date_sorted():
    rows = hm.cheapest_by_date({"2026-12-15": [{"price": 120}],
                                "2026-12-16": [{"price": 80}],
                                "2026-12-17": [{"price": 95}]})
    assert [r["price"] for r in rows] == [80, 95, 120]


def test_cheapest_by_date_skips_empty():
    assert hm.cheapest_by_date({"a": [], "b": [{"price": 0}]}) == []


def test_cheapest_by_date_empty():
    assert hm.cheapest_by_date({}) == []
    assert hm.cheapest_by_date(None) == []


# ── prefs ──────────────────────────────────────────────────────────────────

def test_load_prefs_defaults(store):
    assert hm.load_prefs()["currency"] == "USD"


def test_load_prefs_from_file(store):
    hm.CONFIG_PATH.write_text(json.dumps({"default_city": "Nairobi", "currency": "KES"}),
                              encoding="utf-8")
    p = hm.load_prefs()
    assert p["default_city"] == "Nairobi" and p["currency"] == "KES"


def test_load_prefs_corrupt(store):
    hm.CONFIG_PATH.write_text("{bad", encoding="utf-8")
    assert isinstance(hm.load_prefs(), dict)


def test_dispatcher_uses_default_city(store, browser):
    hm.CONFIG_PATH.write_text(json.dumps({"default_city": "Dubai"}), encoding="utf-8")
    out = hm.hotel_manager({"action": "links", "checkin": "2026-12-15"})
    assert "Dubai" in out


# ── watches ────────────────────────────────────────────────────────────────

def test_watch_add(store, search):
    res = hm.HotelWatch().add(search, 100)
    assert res["ok"] and not res["existing"]
    assert res["item"]["target"] == 100


def test_watch_persists(store, search):
    hm.HotelWatch().add(search, 100)
    assert len(hm.HotelWatch().list()) == 1


def test_watch_dedupe_updates_target(store, search):
    hm.HotelWatch().add(search, 100)
    res = hm.HotelWatch().add(search, 80)
    assert res["existing"] is True
    assert hm.HotelWatch().list()[0]["target"] == 80


def test_watch_remove(store, search):
    wid = hm.HotelWatch().add(search)["item"]["id"]
    assert hm.HotelWatch().remove(wid) is True
    assert hm.HotelWatch().list() == []


def test_watch_remove_unknown(store):
    assert hm.HotelWatch().remove("nope") is False


def test_watch_record_drop(store, search):
    w = hm.HotelWatch().add(search, 100)["item"]
    hw = hm.HotelWatch()
    hw.record(w["id"], 150)
    res = hm.HotelWatch().record(w["id"], 120)
    assert res["dropped"] is True and res["drop"] == 30


def test_watch_record_target_hit(store, search):
    w = hm.HotelWatch().add(search, 100)["item"]
    res = hm.HotelWatch().record(w["id"], 95)
    assert res["target_hit"] is True


def test_watch_record_no_target(store, search):
    w = hm.HotelWatch().add(search)["item"]
    assert hm.HotelWatch().record(w["id"], 95)["target_hit"] is False


def test_watch_record_unknown(store):
    assert hm.HotelWatch().record("nope", 100)["ok"] is False


def test_watch_history_bounded(store, search):
    w = hm.HotelWatch().add(search)["item"]
    for i in range(80):
        hm.HotelWatch().record(w["id"], 100 + i)
    assert len(hm.HotelWatch().get(w["id"])["history"]) == 60


def test_watch_render_empty(store):
    assert "No hotel watches" in hm.HotelWatch().render()


def test_watch_render_lists(store, search):
    hm.HotelWatch().add(search, 100)
    assert "Dubai" in hm.HotelWatch().render()


def test_watch_corrupt_file(store):
    hm.WATCH_PATH.write_text("{bad", encoding="utf-8")
    assert hm.HotelWatch().list() == []


# ── rate limit ─────────────────────────────────────────────────────────────

def test_ledger_first_check_ok(store):
    assert hm.SearchLedger().check()[0] is True


def test_ledger_interval_blocks(store):
    led = hm.SearchLedger()
    led.record()
    ok, reason = hm.SearchLedger().check()
    assert not ok and "wait" in reason


def test_ledger_interval_passes_after_wait(store, clock):
    hm.SearchLedger().record()
    clock.sleep(hm.MIN_SEARCH_INTERVAL_S + 1)
    assert hm.SearchLedger().check()[0] is True


def test_ledger_daily_cap(store, clock):
    for _ in range(hm.DAILY_SEARCH_CAP):
        led = hm.SearchLedger()
        led.record()
        clock.sleep(hm.MIN_SEARCH_INTERVAL_S + 1)
    ok, reason = hm.SearchLedger().check()
    assert not ok and "limit" in reason.lower()


def test_ledger_count_today(store):
    hm.SearchLedger().record()
    assert hm.SearchLedger().count_today() == 1


def test_ledger_corrupt_file(store):
    hm.STATE_PATH.write_text("{bad", encoding="utf-8")
    assert hm.SearchLedger().count_today() == 0


# ── visible search operations ──────────────────────────────────────────────

def test_op_search_site(browser, search, narrator):
    stays = hm.op_search_site("booking", search, narrator, delay=0)
    assert len(stays) == 3


def test_op_search_site_opens_visible(browser, search, narrator):
    hm.op_search_site("booking", search, narrator, delay=0)
    goto = [c for c in browser if c.get("action") == "go_to"]
    assert goto and goto[0]["headless"] is False


def test_op_search_site_narrates(browser, search, narrator):
    hm.op_search_site("booking", search, narrator, delay=0)
    text = narrator.transcript()
    assert "Opening booking" in text and "Reading prices" in text
    assert "3 stay(s) found" in text


def test_op_search_site_unknown(browser, search, narrator):
    assert hm.op_search_site("trivago", search, narrator, delay=0) == []


def test_op_search_site_no_text(monkeypatch, search, narrator):
    monkeypatch.setattr(hm, "_browser", lambda p, player=None: "Could not extract text")
    assert hm.op_search_site("booking", search, narrator, delay=0) == []
    assert "did not return readable text" in narrator.transcript()


def test_op_meta_search(browser, search, narrator):
    stays, urls, notes = hm.op_meta_search(search, ["booking", "google"], narrator, delay=0)
    assert len(urls) == 2 and len(stays) == 6
    assert all("failed" not in n for n in notes)


def test_op_meta_search_survives_site_failure(monkeypatch, search, narrator):
    def flaky(params, player=None):
        if "airbnb" in str(params.get("url", "")):
            raise RuntimeError("site down")
        return PAGE if params.get("action") == "get_text" else "ok"
    monkeypatch.setattr(hm, "_browser", flaky)
    stays, urls, notes = hm.op_meta_search(search, ["booking", "airbnb"], narrator, delay=0)
    assert len(stays) == 3
    assert any("failed" in n for n in notes)
    assert "⚠️" in narrator.transcript()


def test_op_meta_search_narrates_comparison(browser, search, narrator):
    hm.op_meta_search(search, ["booking"], narrator, delay=0)
    assert "Comparing 1 hotel sites" in narrator.transcript()


# ── formatting + reports ───────────────────────────────────────────────────

def test_format_stays_empty():
    assert "No stays parsed" in hm.format_stays([])


def test_format_stays_lists_prices():
    out = hm.format_stays(hm.rank_stays(hm.extract_stays(PAGE, "booking")))
    assert "78" in out and "120" in out


def test_format_stays_limit():
    out = hm.format_stays(hm.extract_stays(PAGE, "booking"), limit=1)
    assert out.count("USD") <= 3


def test_build_report_markdown(search):
    text = hm.build_report(search, hm.extract_stays(PAGE, "booking"), hm.all_urls(search))
    assert "# " in text and "|" in text and "booking" in text


# ── dispatcher ─────────────────────────────────────────────────────────────

def test_help(store):
    out = hm.hotel_manager({"action": "help"})
    assert "Hotel Manager" in out and "compare" in out


def test_help_lists_sites(store):
    assert "booking" in hm.hotel_manager({"action": "status"})


def test_none_params(store):
    assert isinstance(hm.hotel_manager(None), str)


def test_unknown_action(store):
    assert "Unknown hotel action" in hm.hotel_manager({"action": "zzz"})


def test_links_no_browser(store, browser):
    out = hm.hotel_manager({"action": "links", "city": "Dubai", "checkin": "2026-12-15"})
    assert "booking" in out and browser == []


def test_links_validation_error(store):
    assert "Search problem" in hm.hotel_manager({"action": "links", "city": "Dubai"})


def test_search_action(store, browser):
    out = hm.hotel_manager({"action": "search", "city": "Dubai",
                            "checkin": "2026-12-15", "nights": 5})
    assert "78" in out


def test_search_max_price_filter(store, browser):
    out = hm.hotel_manager({"action": "search", "city": "Dubai", "checkin": "2026-12-15",
                            "max_price": 100})
    assert "450" not in out


def test_search_all_filtered_note(store, browser):
    out = hm.hotel_manager({"action": "search", "city": "Dubai", "checkin": "2026-12-15",
                            "max_price": 10})
    assert "outside your price/rating filters" in out


def test_compare_action(store, browser):
    out = hm.hotel_manager({"action": "compare", "city": "Dubai", "checkin": "2026-12-15",
                            "nights": 5, "sites": "booking,google"})
    assert "Checked:" in out and "🏆 Best" in out


def test_compare_total_price(store, browser):
    out = hm.hotel_manager({"action": "compare", "city": "Dubai", "checkin": "2026-12-15",
                            "nights": 5, "sites": "booking"})
    assert "total" in out


def test_compare_save_report(store, browser):
    out = hm.hotel_manager({"action": "compare", "city": "Dubai", "checkin": "2026-12-15",
                            "sites": "booking", "save": True})
    assert "Report saved" in out
    assert list(hm.REPORT_DIR.glob("hotels_*.md"))


def test_deals_alias(store, browser):
    assert "Checked:" in hm.hotel_manager({"action": "deals", "city": "Dubai",
                                           "checkin": "2026-12-15", "sites": "booking"})


def test_watch_action(store, browser):
    out = hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15",
                            "nights": 5, "target": 100})
    assert "Watching" in out and "100" in out


def test_watch_bad_target(store):
    out = hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15",
                            "target": "cheap"})
    assert "number" in out


def test_watch_validation(store):
    assert "Could not set a watch" in hm.hotel_manager({"action": "watch", "city": "Dubai"})


def test_watches_action_empty(store):
    assert "No hotel watches" in hm.hotel_manager({"action": "watches"})


def test_unwatch_needs_id(store):
    assert "Which watch" in hm.hotel_manager({"action": "unwatch"})


def test_unwatch_unknown(store):
    assert "No watch with id" in hm.hotel_manager({"action": "unwatch", "id": "zzz"})


def test_unwatch_removes(store, browser):
    hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15"})
    wid = hm.HotelWatch().list()[0]["id"]
    assert "Removed" in hm.hotel_manager({"action": "unwatch", "id": wid})


def test_check_watches_empty(store):
    assert "No hotel watches" in hm.hotel_manager({"action": "check_watches"})


def test_check_watches_records_price(store, browser):
    hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15",
                      "nights": 5, "target": 100})
    out = hm.hotel_manager({"action": "check_watches"})
    assert "78" in out and "TARGET HIT" in out


def test_check_watches_fires_alert(store, browser, monkeypatch):
    from core import alerts
    calls = []
    monkeypatch.setattr(alerts, "notify",
                        lambda *a, **k: calls.append(a) or {"ok": True, "results": {}})
    hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15",
                      "target": 100})
    hm.hotel_manager({"action": "check_watches"})
    assert calls and "Hotel price alert" in calls[0][0]


def test_check_watches_alert_failure_is_soft(store, browser, monkeypatch):
    from core import alerts
    monkeypatch.setattr(alerts, "notify",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("channels down")))
    hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15",
                      "target": 100})
    out = hm.hotel_manager({"action": "check_watches"})
    assert "TARGET HIT" in out


def test_check_watches_survives_site_error(store, browser, monkeypatch):
    hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15"})
    monkeypatch.setattr(hm, "op_search_site",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = hm.hotel_manager({"action": "check_watches"})
    assert "check failed" in out


def test_check_watches_no_price(store, browser, monkeypatch):
    hm.hotel_manager({"action": "watch", "city": "Dubai", "checkin": "2026-12-15"})
    monkeypatch.setattr(hm, "op_search_site", lambda *a, **k: [])
    assert "no price parsed" in hm.hotel_manager({"action": "check_watches"})


def test_book_requires_confirm(store, browser):
    out = hm.hotel_manager({"action": "book", "city": "Dubai", "checkin": "2026-12-15"})
    assert hm.CONFIRM_TEXT in out and browser == []


def test_book_with_confirm_opens_site(store, browser):
    out = hm.hotel_manager({"action": "book", "city": "Dubai", "checkin": "2026-12-15",
                            "confirm": hm.CONFIRM_TEXT})
    assert "Opened booking" in out and "won't touch card data" in out
    assert browser and browser[0]["headless"] is False


def test_flexible_action(store, browser):
    out = hm.hotel_manager({"action": "flexible", "city": "Dubai", "checkin": "2026-12-15",
                            "nights": 2, "flex_days": 2})
    assert "Cheapest check-ins" in out and "cheapest" in out


def test_flexible_bad_days(store):
    assert "whole number" in hm.hotel_manager({"action": "flexible", "city": "Dubai",
                                               "checkin": "2026-12-15", "flex_days": "lots"})


def test_flexible_out_of_range(store):
    assert "between 0 and" in hm.hotel_manager({"action": "flexible", "city": "Dubai",
                                               "checkin": "2026-12-15", "flex_days": 99})


def test_flexible_no_prices(store, browser, monkeypatch):
    monkeypatch.setattr(hm, "op_search_site", lambda *a, **k: [])
    assert "No prices parsed" in hm.hotel_manager({"action": "flexible", "city": "Dubai",
                                                  "checkin": "2026-12-15", "flex_days": 1})


def test_report_action(store, browser):
    out = hm.hotel_manager({"action": "report", "city": "Dubai", "checkin": "2026-12-15",
                            "sites": "booking"})
    assert "|" in out


def test_report_save(store, browser):
    out = hm.hotel_manager({"action": "report", "city": "Dubai", "checkin": "2026-12-15",
                            "sites": "booking", "save": True})
    assert "Report saved" in out


def test_rate_limit_message(store, browser):
    hm.hotel_manager({"action": "search", "city": "Dubai", "checkin": "2026-12-15"})
    out = hm.hotel_manager({"action": "search", "city": "Dubai", "checkin": "2026-12-15"})
    assert "⏳" in out


def test_dispatcher_is_crash_proof(store, monkeypatch):
    monkeypatch.setattr(hm, "build_search",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("internal")))
    out = hm.hotel_manager({"action": "search", "city": "Dubai", "checkin": "2026-12-15"})
    assert "problem" in out and "session is still running" in out


def test_dispatcher_survives_broken_player(store, browser):
    class P:
        def write_log(self, t):
            raise RuntimeError("ui down")
    out = hm.hotel_manager({"action": "search", "city": "Dubai",
                            "checkin": "2026-12-15"}, player=P())
    assert isinstance(out, str) and "78" in out
