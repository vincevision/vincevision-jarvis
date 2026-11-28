"""Offline tests for the multi-site flight manager.

No network and no browser: every browser call goes through a monkeypatched
delegate, and a virtual clock makes rate limits and watches deterministic.
"""

from datetime import datetime

import pytest

from actions import flight_manager as fm


TODAY = datetime(2026, 11, 28)          # a Saturday


class FakeClock:
    def __init__(self, start=1_800_000_000.0):
        self.t = start

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(fm, "time", c)
    return c


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "WATCH_PATH", tmp_path / "watches.json")
    monkeypatch.setattr(fm, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(fm, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(fm, "CONFIG_PATH", tmp_path / "flights.json")
    return tmp_path


@pytest.fixture
def search():
    return fm.build_search({"origin": "Nairobi", "destination": "Dubai",
                            "date": "2026-12-15", "return_date": "2026-12-22"}, TODAY)


PAGE = """Emirates
8:00 AM - 4:30 PM
Nonstop
5 hr 30 min
NBO-DXB
$450
Kenya Airways
1 stop
9 hr 15 min
$380
Qatar Airways
2 stops
18 hr 40 min
$295"""


@pytest.fixture
def browser(monkeypatch, clock):
    """Fake browser returning a realistic results page."""
    log = []

    def fake(params, player=None):
        log.append(params)
        if params.get("action") == "get_text":
            return PAGE
        return "ok"

    monkeypatch.setattr(fm, "_browser", fake)
    return log


# ── airports ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Nairobi", "NBO"), ("JKIA", "NBO"), ("nbo", "NBO"), ("NBO", "NBO"),
    ("Mombasa", "MBA"), ("Dubai", "DXB"), ("london", "LHR"), ("nyc", "JFK"),
    ("Cape Town", "CPT"), ("Zanzibar", "ZNZ"), ("nairobi kenya", "NBO"),
    ("XYZ", "XYZ"), ("", ""), (None, ""), ("Nowhereville", ""),
])
def test_resolve_airport(raw, expected):
    assert fm.resolve_airport(raw) == expected


def test_airport_suggestions():
    sug = fm.airport_suggestions("nai")
    assert any("Nairobi" in s for s in sug)


def test_airport_suggestions_empty():
    assert fm.airport_suggestions("") == []


# ── dates ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-12-15", "2026-12-15"),
    ("today", "2026-11-28"),
    ("tomorrow", "2026-11-29"),
    ("+10d", "2026-12-08"),
    ("+3 days", "2026-12-01"),
    ("in 5 days", "2026-12-03"),
    ("in 3 weeks", "2026-12-19"),
    ("in 2 months", "2027-01-27"),
    ("15/12/2026", "2026-12-15"),
    ("15.12.2026", "2026-12-15"),
    ("15 December 2026", "2026-12-15"),
    ("15 Dec 2026", "2026-12-15"),
    ("Dec 15", "2026-12-15"),
    ("december 15", "2026-12-15"),
    ("15 dec", "2026-12-15"),
    ("next friday", "2026-12-11"),   # 'next X' = following week
    ("friday", "2026-12-04"),        # bare weekday = the upcoming one
    ("monday", "2026-11-30"),
    ("saturday", "2026-12-05"),      # today is Saturday -> next week
    ("next saturday", "2026-12-05"),
])
def test_parse_date(raw, expected):
    assert fm.parse_date(raw, TODAY) == expected


@pytest.mark.parametrize("raw", ["", None, "garbage", "2026-13-45", "notadate"])
def test_parse_date_invalid(raw):
    assert fm.parse_date(raw, TODAY) == ""


def test_parse_date_past_month_rolls_forward():
    # 'jan 10' said in November means next January.
    assert fm.parse_date("jan 10", TODAY) == "2027-01-10"


def test_parse_date_explicit_past_year_kept():
    assert fm.parse_date("10 jan 2020", TODAY) == "2020-01-10"


def test_parse_date_datetime_input():
    assert fm.parse_date(datetime(2026, 12, 15), TODAY) == "2026-12-15"


def test_date_grid():
    grid = fm.date_grid("2026-12-15", 2)
    assert grid == ["2026-12-13", "2026-12-14", "2026-12-15", "2026-12-16", "2026-12-17"]


def test_date_grid_zero():
    assert fm.date_grid("2026-12-15", 0) == ["2026-12-15"]


def test_date_grid_clamped():
    assert len(fm.date_grid("2026-12-15", 99)) == 2 * fm.MAX_FLEX_DAYS + 1


def test_date_grid_bad_date():
    assert fm.date_grid("nope", 3) == []


def test_days_until():
    assert fm.days_until("2026-12-15", TODAY) == 17
    assert fm.days_until("bad", TODAY) == 0


# ── search validation ───────────────────────────────────────────────────────

def test_build_search_ok(search):
    assert search["ok"]
    assert (search["origin"], search["destination"]) == ("NBO", "DXB")
    assert search["trip"] == "roundtrip" and search["cabin"] == "economy"


def test_build_search_oneway_inferred():
    s = fm.build_search({"origin": "NBO", "destination": "DXB", "date": "2026-12-15"}, TODAY)
    assert s["ok"] and s["trip"] == "oneway"


def test_build_search_missing_route():
    s = fm.build_search({"date": "2026-12-15"}, TODAY)
    assert not s["ok"] and len(s["errors"]) >= 2


def test_build_search_same_airport():
    s = fm.build_search({"origin": "NBO", "destination": "Nairobi", "date": "2026-12-15"}, TODAY)
    assert not s["ok"] and "same airport" in " ".join(s["errors"])


def test_build_search_missing_date():
    s = fm.build_search({"origin": "NBO", "destination": "DXB"}, TODAY)
    assert not s["ok"] and "departure date" in " ".join(s["errors"])


def test_build_search_return_before_depart():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "return_date": "2026-12-01"}, TODAY)
    assert not s["ok"] and "before the departure" in " ".join(s["errors"])


def test_build_search_roundtrip_needs_return():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "trip": "roundtrip"}, TODAY)
    assert not s["ok"] and "needs a return date" in " ".join(s["errors"])


def test_build_search_bad_trip():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "trip": "teleport"}, TODAY)
    assert not s["ok"]


@pytest.mark.parametrize("pax", [0, 10, "abc"])
def test_build_search_bad_passengers(pax):
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "passengers": pax}, TODAY)
    assert not s["ok"] and "Passengers" in " ".join(s["errors"])


def test_build_search_cabin_alias():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "cabin": "premium economy"}, TODAY)
    assert s["ok"] and s["cabin"] == "premium"


def test_build_search_bad_cabin():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "cabin": "cargo"}, TODAY)
    assert not s["ok"]


@pytest.mark.parametrize("raw,expected", [("direct", "nonstop"), ("non-stop", "nonstop"),
                                          ("1", "1stop"), ("any", "any")])
def test_build_search_stops_aliases(raw, expected):
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "stops": raw}, TODAY)
    assert s["ok"] and s["stops"] == expected


def test_build_search_bad_stops():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "stops": "maybe"}, TODAY)
    assert not s["ok"]


def test_build_search_budget():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "max_price": "600"}, TODAY)
    assert s["ok"] and s["max_price"] == 600.0


def test_build_search_negative_budget():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "budget": -5}, TODAY)
    assert not s["ok"]


def test_build_search_bad_budget():
    s = fm.build_search({"origin": "NBO", "destination": "DXB",
                         "date": "2026-12-15", "max_price": "cheap"}, TODAY)
    assert not s["ok"]


def test_build_search_currency_default_and_custom():
    base = {"origin": "NBO", "destination": "DXB", "date": "2026-12-15"}
    assert fm.build_search(base, TODAY)["currency"] == "USD"
    assert fm.build_search(dict(base, currency="kes"), TODAY)["currency"] == "KES"
    assert fm.build_search(dict(base, currency="!!"), TODAY)["currency"] == "USD"


# ── site list ───────────────────────────────────────────────────────────────

def test_site_list_default():
    assert fm._site_list(None) == list(fm.SITES)
    assert fm._site_list("all") == list(fm.SITES)


def test_site_list_aliases_and_dedupe():
    assert fm._site_list("Google Flights, kayak kayak") == ["google", "kayak"]


def test_site_list_filters_unknown():
    assert fm._site_list("kayak, bogus, skyscanner.net") == ["kayak", "skyscanner"]


def test_site_list_capped():
    assert len(fm._site_list(",".join(fm.SITES))) <= fm.MAX_SITES


def test_site_list_all_unknown_falls_back():
    assert fm._site_list("bogus") == list(fm.SITES)


# ── deep links ──────────────────────────────────────────────────────────────

def test_all_sites_have_urls(search):
    urls = fm.all_urls(search)
    assert set(urls) == set(fm.SITES)
    assert all(u.startswith("https://") for u in urls.values())


def test_kayak_roundtrip(search):
    url = fm.build_url("kayak", search)
    assert "/flights/NBO-DXB/2026-12-15/2026-12-22" in url
    assert "sort=price_a" in url


def test_kayak_oneway(search):
    s = dict(search, trip="oneway", **{"return": ""})
    url = fm.build_url("kayak", s)
    assert url.endswith("/flights/NBO-DXB/2026-12-15?sort=price_a")


def test_kayak_pax_cabin(search):
    s = dict(search, passengers=2, cabin="business")
    assert "/2adults/business" in fm.build_url("kayak", s)


def test_kayak_nonstop(search):
    assert "stops=0" in fm.build_url("kayak", dict(search, stops="nonstop"))


def test_momondo(search):
    assert "momondo.com/flight-search/NBO-DXB/2026-12-15" in fm.build_url("momondo", search)


def test_google_flights_no_stale_blob(search):
    url = fm.build_url("google", search)
    assert "tfs=" not in url                     # the old hardcoded IST-LHR blob
    assert "NBO" in url and "DXB" in url
    assert "2026-12-15" in url and "2026-12-22" in url
    assert "curr=USD" in url


def test_google_nonstop(search):
    assert "nonstop" in fm.build_url("google", dict(search, stops="nonstop"))


def test_skyscanner(search):
    url = fm.build_url("skyscanner", search)
    assert "/transport/flights/nbo/dxb/261215/261222/" in url
    assert "rtn=1" in url and "cabinclass=economy" in url


def test_skyscanner_oneway_cabin(search):
    s = dict(search, trip="oneway", **{"return": ""}, cabin="business")
    url = fm.build_url("skyscanner", s)
    assert "rtn=0" in url and "cabinclass=business" in url
    assert "261222" not in url


def test_skyscanner_premium(search):
    assert "premiumeconomy" in fm.build_url("skyscanner", dict(search, cabin="premium"))


def test_expedia(search):
    url = fm.build_url("expedia", search)
    assert "trip=roundtrip" in url
    assert "departure:12/15/2026" in url and "departure:12/22/2026" in url
    assert "adults:1" in url


def test_expedia_oneway(search):
    url = fm.build_url("expedia", dict(search, trip="oneway", **{"return": ""}))
    assert "trip=oneway" in url and "leg2" not in url


def test_kiwi(search):
    url = fm.build_url("kiwi", search)
    assert "/search/results/nbo-dxb/2026-12-15/2026-12-22" in url
    assert "cabinClass=ECONOMY" in url


def test_booking(search):
    url = fm.build_url("booking", search)
    assert "type=ROUNDTRIP" in url and "depart=2026-12-15" in url
    assert "return=2026-12-22" in url


def test_booking_oneway(search):
    url = fm.build_url("booking", dict(search, trip="oneway", **{"return": ""}))
    assert "type=ONEWAY" in url and "return=" not in url


def test_booking_premium(search):
    assert "PREMIUM_ECONOMY" in fm.build_url("booking", dict(search, cabin="premium"))


def test_trip(search):
    url = fm.build_url("trip", search)
    assert "dcity=nbo" in url and "acity=dxb" in url
    assert "triptype=rt" in url and "rdate=2026-12-22" in url


def test_trip_oneway_first(search):
    url = fm.build_url("trip", dict(search, trip="oneway", **{"return": ""}, cabin="first"))
    assert "triptype=ow" in url and "class=f" in url and "rdate" not in url


def test_unknown_site_url(search):
    assert fm.build_url("bogus", search) == ""


def test_currency_propagates(search):
    s = dict(search, currency="KES")
    assert "curr=KES" in fm.build_url("google", s)
    assert "currency=KES" in fm.build_url("skyscanner", s)
    assert "currency=KES" in fm.build_url("booking", s)


# ── price parsing ───────────────────────────────────────────────────────────

def test_parse_prices_symbols():
    assert fm.parse_prices("$450 €1,200 £99.50 ₹5000 ¥12000") == [450, 1200, 99.5, 5000, 12000]


def test_parse_prices_iso():
    assert fm.parse_prices("USD 450 KES 45,000 AED 1200") == [450, 45000, 1200]


def test_parse_prices_thousands_and_spaces():
    assert fm.parse_prices("$1,234.50 and $12 500") == [1234.5, 12500]


def test_parse_prices_ignores_duration():
    """Regression: bare 'R' (ZAR) must not match the 'r' in '5 hr 30 min'."""
    assert fm.parse_prices("5 hr 30 min") == []
    assert fm.parse_prices("18 hours 40 minutes") == []


def test_parse_prices_bare_rand():
    assert fm.parse_prices("R 2500") == [2500]


def test_parse_prices_empty():
    assert fm.parse_prices("") == []
    assert fm.parse_prices(None) == []
    assert fm.parse_prices("no money here") == []


@pytest.mark.parametrize("text,expected", [
    ("5 hr 30 min", 330), ("5h30m", 330), ("18 hours 40 minutes", 1120),
    ("9 hrs 15 mins", 555), ("6h", 360), ("no duration", 0),
])
def test_duration_minutes(text, expected):
    """Regression: 'hr' must not be matched as 'h', dropping the minutes."""
    assert fm._duration_minutes(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Nonstop", 0), ("non-stop", 0), ("Direct", 0),
    ("1 stop", 1), ("2 stops", 2), ("3+ stops", 3), ("unknown", -1),
])
def test_stops_count(text, expected):
    assert fm._stops_count(text) == expected


# ── offer extraction ────────────────────────────────────────────────────────

def test_extract_offers_basic():
    offers = fm.extract_offers(PAGE, "kayak")
    assert len(offers) == 3
    assert [o["price"] for o in offers] == [450, 380, 295]
    assert [o["airline"] for o in offers] == ["Emirates", "Kenya Airways", "Qatar Airways"]
    assert [o["stops"] for o in offers] == [0, 1, 2]
    assert [o["duration_min"] for o in offers] == [330, 555, 1120]
    assert all(o["site"] == "kayak" for o in offers)


def test_extract_offers_no_context_bleed():
    """Regression: offer 2 must not inherit offer 1's 'Nonstop'."""
    offers = fm.extract_offers(PAGE, "kayak")
    assert offers[1]["stops"] == 1


def test_extract_offers_dedupes():
    offers = fm.extract_offers("$450\n$450", "kayak")
    assert len(offers) == 1


def test_extract_offers_limit():
    text = "\n".join(f"${100 + i}" for i in range(30))
    assert len(fm.extract_offers(text, "kayak", limit=5)) == 5


def test_extract_offers_empty():
    assert fm.extract_offers("", "kayak") == []
    assert fm.extract_offers("nothing to see", "kayak") == []


def test_extract_offers_currency():
    offers = fm.extract_offers("KES 45,000", "kayak", "KES")
    assert offers[0]["currency"] == "KES" and offers[0]["price"] == 45000


# ── ranking ────────────────────────────────────────────────────────────────

def test_score_price_dominates():
    cheap = {"price": 200, "stops": 0, "duration_min": 300}
    pricey = {"price": 900, "stops": 0, "duration_min": 300}
    assert fm.score_offer(cheap) < fm.score_offer(pricey)


def test_score_stops_penalty():
    o = {"price": 300, "stops": 2, "duration_min": 0}
    assert fm.score_offer(o) == 300 + 2 * 60


def test_score_duration_penalty():
    o = {"price": 300, "stops": 0, "duration_min": 600}   # 10h vs 6h baseline
    assert fm.score_offer(o) == 300 + 4 * 12


def test_score_airline_preference():
    o = {"price": 400, "airline": "Emirates", "stops": 0}
    assert fm.score_offer(o, {"airlines": ["Emirates"]}) == 360
    assert fm.score_offer(o, {"airlines": ["Qatar"]}) == 425


def test_score_bag_penalty():
    o = {"price": 300, "stops": 0}
    assert fm.score_offer(o, {"require_bag": True}) == 370
    assert fm.score_offer(dict(o, bag_included=True), {"require_bag": True}) == 300


def test_rank_offers_sorted_by_score():
    """Ranking is score-based, not raw price: a cheap 2-stop 18h itinerary
    legitimately ranks below a pricier nonstop."""
    offers = fm.extract_offers(PAGE, "kayak")
    ranked = fm.rank_offers(offers)
    assert [r["score"] for r in ranked] == sorted(r["score"] for r in ranked)
    assert all("score" in r for r in ranked)
    assert ranked[0]["airline"] == "Emirates"      # nonstop, 5h30


def test_rank_offers_preference_reorders():
    offers = fm.extract_offers(PAGE, "kayak")
    ranked = fm.rank_offers(offers, {"airlines": ["Emirates"]})
    assert ranked[0]["airline"] == "Emirates"


def test_rank_offers_budget_filter():
    offers = fm.extract_offers(PAGE, "kayak")
    ranked = fm.rank_offers(offers, max_price=400)
    assert sorted(r["price"] for r in ranked) == [295, 380]


def test_rank_offers_empty():
    assert fm.rank_offers([]) == []
    assert fm.rank_offers(None) == []


def test_cheapest_by_date():
    rows = fm.cheapest_by_date({
        "2026-12-15": [{"price": 450, "site": "kayak"}],
        "2026-12-16": [{"price": 250, "site": "google", "airline": "Emirates"}],
        "2026-12-17": [],
    })
    assert rows[0]["date"] == "2026-12-16" and rows[0]["price"] == 250
    assert len(rows) == 2


def test_cheapest_by_date_empty():
    assert fm.cheapest_by_date({}) == []
    assert fm.cheapest_by_date(None) == []


@pytest.mark.parametrize("days,fragment", [
    (-1, "past"), (3, "Under a week"), (14, "Getting close"),
    (45, "sweet spot"), (90, "Plenty of time"), (200, "Very early"),
])
def test_buying_advice(days, fragment):
    assert fragment in fm.buying_advice(days)


# ── price watches ───────────────────────────────────────────────────────────

def test_watch_add(store, search):
    pw = fm.PriceWatch()
    res = pw.add(search, target=500, now=1000.0)
    assert res["ok"] and not res["existing"]
    assert res["item"]["target"] == 500
    assert len(fm.PriceWatch().list()) == 1


def test_watch_dedupe_updates_target(store, search):
    pw = fm.PriceWatch()
    pw.add(search, target=500, now=1000.0)
    res = fm.PriceWatch().add(search, target=400, now=2000.0)
    assert res["existing"] and res["item"]["target"] == 400
    assert len(fm.PriceWatch().list()) == 1


def test_watch_get_remove(store, search):
    pw = fm.PriceWatch()
    wid = pw.add(search, now=1000.0)["item"]["id"]
    assert fm.PriceWatch().get(wid) is not None
    assert fm.PriceWatch().remove(wid)
    assert not fm.PriceWatch().remove(wid)
    assert fm.PriceWatch().get(wid) is None


def test_watch_record_drop(store, search):
    pw = fm.PriceWatch()
    wid = pw.add(search, now=1000.0)["item"]["id"]
    fm.PriceWatch().record(wid, 500, "kayak", now=1100.0)
    res = fm.PriceWatch().record(wid, 420, "kayak", now=1200.0)
    assert res["dropped"] and res["drop"] == 80
    assert res["previous"] == 500


def test_watch_record_rise(store, search):
    pw = fm.PriceWatch()
    wid = pw.add(search, now=1000.0)["item"]["id"]
    fm.PriceWatch().record(wid, 400, now=1100.0)
    res = fm.PriceWatch().record(wid, 480, now=1200.0)
    assert not res["dropped"] and res["drop"] == -80


def test_watch_target_hit(store, search):
    pw = fm.PriceWatch()
    wid = pw.add(search, target=400, now=1000.0)["item"]["id"]
    assert not fm.PriceWatch().record(wid, 450, now=1100.0)["target_hit"]
    assert fm.PriceWatch().record(wid, 380, now=1200.0)["target_hit"]


def test_watch_record_unknown(store):
    assert not fm.PriceWatch().record("nope", 100)["ok"]


def test_watch_history_capped(store, search):
    pw = fm.PriceWatch()
    wid = pw.add(search, now=1000.0)["item"]["id"]
    for i in range(70):
        fm.PriceWatch().record(wid, 400 + i, now=1100.0 + i)
    assert len(fm.PriceWatch().get(wid)["history"]) == 60


def test_watch_render(store, search):
    assert "No flight price watches" in fm.PriceWatch().render()
    fm.PriceWatch().add(search, target=500, now=1000.0)
    out = fm.PriceWatch().render()
    assert "NBO→DXB" in out and "target USD 500" in out


def test_watch_corrupt_file(store):
    fm.WATCH_PATH.write_text("{bad")
    assert fm.PriceWatch().list() == []


# ── search ledger ───────────────────────────────────────────────────────────

def test_ledger_first_search_allowed(store):
    assert fm.SearchLedger().check(now=1000.0) == (True, "")


def test_ledger_interval(store):
    led = fm.SearchLedger()
    led.record(now=1000.0)
    ok, reason = fm.SearchLedger().check(now=1001.0)
    assert not ok and "wait" in reason
    assert fm.SearchLedger().check(now=1000.0 + fm.MIN_SEARCH_INTERVAL_S + 1)[0]


def test_ledger_daily_cap(store):
    led = fm.SearchLedger()
    for i in range(fm.DAILY_SEARCH_CAP):
        led.record(now=1000.0 + i * 10)
    ok, reason = fm.SearchLedger().check(now=1000.0 + fm.DAILY_SEARCH_CAP * 10)
    assert not ok and "Daily flight-search limit" in reason


def test_ledger_new_day_resets(store):
    led = fm.SearchLedger()
    led.record(now=1_800_000_000.0)
    assert fm.SearchLedger().count_today(now=1_800_000_000.0 + 172800) == 0


def test_ledger_corrupt(store):
    fm.STATE_PATH.write_text("bad")
    assert fm.SearchLedger().count_today(now=1000.0) == 0


# ── formatting / report ─────────────────────────────────────────────────────

def test_format_offers():
    ranked = fm.rank_offers(fm.extract_offers(PAGE, "kayak"))
    out = fm.format_offers(ranked)
    assert "Best offers" in out and "USD 295" in out and "nonstop" in out


def test_format_offers_empty():
    assert "No offers parsed" in fm.format_offers([])


def test_build_report(search):
    ranked = fm.rank_offers(fm.extract_offers(PAGE, "kayak"))
    text = fm.build_report(search, ranked, fm.all_urls(search), now=1_800_000_000.0)
    assert "# Flight comparison — NBO → DXB" in text
    assert "| # | Price |" in text and "295" in text
    assert "[kayak](" in text and "## When to buy" in text


def test_build_report_no_offers(search):
    text = fm.build_report(search, [], {"kayak": "https://x"}, now=1_800_000_000.0)
    assert "No offers parsed automatically" in text


# ── browser operations ──────────────────────────────────────────────────────

def test_op_search_site(browser, search):
    offers = fm.op_search_site("kayak", search, delay=0)
    assert len(offers) == 3
    assert browser[0]["action"] == "go_to" and "kayak.com" in browser[0]["url"]
    assert browser[1]["action"] == "get_text" and browser[1]["limit"] == 40000


def test_op_search_site_unknown(browser, search):
    assert fm.op_search_site("bogus", search, delay=0) == []


def test_op_search_site_no_text(monkeypatch, search, clock):
    monkeypatch.setattr(fm, "_browser",
                        lambda p, player=None: "Could not extract text: boom"
                        if p["action"] == "get_text" else "ok")
    assert fm.op_search_site("kayak", search, delay=0) == []


def test_op_meta_search(browser, search):
    offers, urls, notes = fm.op_meta_search(search, ["kayak", "google"], delay=0)
    assert len(offers) == 6                       # 3 per site
    assert set(urls) == {"kayak", "google"}
    assert notes == ["kayak: 3 offer(s)", "google: 3 offer(s)"]


def test_op_meta_search_survives_failure(monkeypatch, search, clock):
    def flaky(params, player=None):
        if params["action"] == "go_to" and "kayak" in params["url"]:
            raise RuntimeError("site down")
        return PAGE if params["action"] == "get_text" else "ok"

    monkeypatch.setattr(fm, "_browser", flaky)
    offers, urls, notes = fm.op_meta_search(search, ["kayak", "google"], delay=0)
    assert len(offers) == 3
    assert "failed" in notes[0]


# ── dispatcher ──────────────────────────────────────────────────────────────

def test_dispatch_help():
    out = fm.flight_manager({"action": "help"})
    assert "Flight Manager" in out and "kayak" in out and "compare" in out


def test_dispatch_airports():
    assert "NBO" in fm.flight_manager({"action": "airports", "query": "Nairobi"})


def test_dispatch_airports_unknown():
    assert "Couldn't resolve" in fm.flight_manager({"action": "airports", "query": "zzzzz"})


def test_dispatch_advice():
    out = fm.flight_manager({"action": "advice", "date": "2026-12-15"})
    assert "day(s) away" in out


def test_dispatch_advice_needs_date():
    assert "Which departure date" in fm.flight_manager({"action": "advice"})


def test_dispatch_unknown(store):
    assert "Unknown flight action" in fm.flight_manager({"action": "zzz"})


def test_dispatch_validation_error(store):
    out = fm.flight_manager({"action": "compare", "origin": "NBO"})
    assert "Search problem" in out


def test_dispatch_links_no_browser(search, store, monkeypatch):
    calls = []
    monkeypatch.setattr(fm, "_browser", lambda p, player=None: calls.append(p) or "ok")
    out = fm.flight_manager({"action": "links", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak,google"})
    assert "kayak:" in out and "google:" in out
    assert calls == []                            # links never opens a browser


def test_dispatch_search(browser, store):
    out = fm.flight_manager({"action": "search", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak"})
    assert "USD 295" in out and "kayak" in out


def test_dispatch_search_budget_note(browser, store):
    out = fm.flight_manager({"action": "search", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak", "max_price": 100})
    assert "above your USD 100 cap" in out


def test_dispatch_compare(browser, store):
    out = fm.flight_manager({"action": "compare", "origin": "Nairobi",
                             "destination": "Dubai", "date": "2026-12-15",
                             "sites": "kayak,google"})
    assert "2 sites" in out and "🏆 Best" in out and "Checked:" in out


def test_dispatch_compare_saves_report(browser, store):
    out = fm.flight_manager({"action": "compare", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak", "save": "true"})
    assert "Report saved" in out
    assert list((store / "reports").glob("flights_*.md"))


def test_dispatch_rate_limited(browser, store, monkeypatch):
    # Zero page-settle delay so the virtual clock doesn't advance past the
    # minimum search interval on its own.
    monkeypatch.setattr(fm, "SITE_DELAY_S", 0)
    p = {"action": "search", "origin": "NBO", "destination": "DXB",
         "date": "2026-12-15", "sites": "kayak"}
    fm.flight_manager(p)
    assert "wait" in fm.flight_manager(p)


def test_dispatch_watch_and_list(browser, store):
    out = fm.flight_manager({"action": "watch", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "target": 400})
    assert "Watching [" in out and "400" in out
    assert "NBO→DXB" in fm.flight_manager({"action": "watches"})


def test_dispatch_watch_bad_target(store):
    out = fm.flight_manager({"action": "watch", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "target": "cheap"})
    assert "target must be a number" in out


def test_dispatch_watch_invalid_route(store):
    assert "Could not set a watch" in fm.flight_manager({"action": "watch", "origin": "NBO"})


def test_dispatch_unwatch(browser, store):
    fm.flight_manager({"action": "watch", "origin": "NBO", "destination": "DXB",
                       "date": "2026-12-15"})
    wid = fm.PriceWatch().list()[0]["id"]
    assert "Removed watch" in fm.flight_manager({"action": "unwatch", "id": wid})
    assert "No watch with id" in fm.flight_manager({"action": "unwatch", "id": "zzz"})
    assert "Which watch" in fm.flight_manager({"action": "unwatch"})


def test_dispatch_check_watches_empty(store):
    assert "No watches to check" in fm.flight_manager({"action": "check_watches"})


def test_dispatch_check_watches_alert(browser, store):
    fm.flight_manager({"action": "watch", "origin": "NBO", "destination": "DXB",
                       "date": "2026-12-15", "target": 300})
    out = fm.flight_manager({"action": "check_watches"})
    assert "TARGET HIT" in out and "1 alert(s)" in out


def test_dispatch_flexible(browser, store):
    out = fm.flight_manager({"action": "flexible", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "flex_days": 1, "sites": "kayak"})
    assert "Cheapest days" in out and "← cheapest" in out
    assert "2026-12-14" in out and "2026-12-16" in out


def test_dispatch_flexible_shifts_return(browser, store):
    fm.flight_manager({"action": "flexible", "origin": "NBO", "destination": "DXB",
                       "date": "2026-12-15", "return_date": "2026-12-22",
                       "flex_days": 1, "sites": "kayak"})
    urls = [c["url"] for c in browser if c.get("action") == "go_to"]
    # 7-day trip span preserved when the outbound date shifts by +1.
    assert any("2026-12-16/2026-12-23" in u for u in urls)


def test_dispatch_report(browser, store):
    out = fm.flight_manager({"action": "report", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak"})
    assert "# Flight comparison" in out


def test_dispatch_report_save(browser, store):
    out = fm.flight_manager({"action": "report", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak", "save": "true"})
    assert "Report saved" in out


def test_dispatch_book_needs_confirm(browser, store):
    out = fm.flight_manager({"action": "book", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15"})
    assert fm.CONFIRM_TEXT in out
    assert browser == []                          # nothing opened without consent


def test_dispatch_book_opens_only(browser, store):
    out = fm.flight_manager({"action": "book", "origin": "NBO", "destination": "DXB",
                             "date": "2026-12-15", "sites": "kayak",
                             "confirm": fm.CONFIRM_TEXT})
    assert "Opened kayak" in out and "won't enter card data" in out
    assert len(browser) == 1 and browser[0]["action"] == "go_to"


def test_load_prefs_defaults(store):
    cfg = fm.load_prefs()
    assert cfg["home_airport"] == "" and cfg["currency"] == "USD"


def test_load_prefs_from_file(store):
    fm.CONFIG_PATH.write_text('{"home_airport": "NBO", "currency": "KES"}')
    cfg = fm.load_prefs()
    assert cfg["home_airport"] == "NBO" and cfg["currency"] == "KES"


def test_load_prefs_corrupt(store):
    fm.CONFIG_PATH.write_text("{bad")
    assert fm.load_prefs()["currency"] == "USD"


def test_dispatch_uses_home_airport(browser, store):
    fm.CONFIG_PATH.write_text('{"home_airport": "NBO", "currency": "KES"}')
    out = fm.flight_manager({"action": "links", "destination": "Dubai",
                             "date": "2026-12-15", "sites": "google"})
    assert "NBO → DXB" in out and "curr=KES" in out


def test_dispatch_explicit_origin_wins(browser, store):
    fm.CONFIG_PATH.write_text('{"home_airport": "NBO"}')
    out = fm.flight_manager({"action": "links", "origin": "Mombasa",
                             "destination": "Dubai", "date": "2026-12-15",
                             "sites": "kayak"})
    assert "MBA → DXB" in out


def test_dispatch_deep_delegates(monkeypatch, store):
    seen = {}

    def fake_deep(o, d, date, ret, pax, cabin, player=None, speak=None):
        seen.update(origin=o, destination=d, date=date, cabin=cabin)
        return "deep result"

    monkeypatch.setattr(fm, "_deep_parse", fake_deep)
    out = fm.flight_manager({"action": "deep", "origin": "Nairobi", "destination": "Dubai",
                             "date": "2026-12-15"})
    assert out == "deep result"
    assert seen["origin"] == "NBO" and seen["destination"] == "DXB"
