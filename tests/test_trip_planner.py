"""Offline tests for the trip planner (actions/trip_planner.py).

No network: flight/hotel searches are stubbed. Verifies budgets, itineraries,
checklists, saving, exports, and that a failing sub-search never crashes it.
"""

import json
from datetime import datetime

import pytest

from actions import trip_planner as tp


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(tp, "PLAN_PATH", tmp_path / "trips.json")
    monkeypatch.setenv("JARVIS_PACE", "0")
    monkeypatch.setenv("JARVIS_SHOW_ME", "1")
    return tmp_path


@pytest.fixture
def trip():
    return tp.build_trip({"destination": "Dubai", "origin": "Nairobi",
                          "date": "2026-12-15", "nights": 5,
                          "travellers": 2, "budget": 1500})


@pytest.fixture
def no_search(monkeypatch):
    """Keep 'plan' offline: stub both managers."""
    from actions import flight_manager as fm, hotel_manager as hm
    monkeypatch.setattr(fm, "flight_manager", lambda *a, **k: "Flight results stub")
    monkeypatch.setattr(hm, "hotel_manager", lambda *a, **k: "Hotel results stub")
    monkeypatch.setattr(fm, "op_search_site",
                        lambda *a, **k: [{"price": 380.0, "site": "kayak"}])
    monkeypatch.setattr(hm, "op_search_site",
                        lambda *a, **k: [{"price": 90.0, "site": "booking"}])


# ── build_trip validation ──────────────────────────────────────────────────

def test_build_trip_ok(trip):
    assert trip["ok"] is True
    assert trip["end"] == "2026-12-20" and trip["nights"] == 5


def test_build_trip_needs_destination():
    t = tp.build_trip({"date": "2026-12-15", "nights": 3})
    assert not t["ok"] and any("destination" in e.lower() for e in t["errors"])


def test_build_trip_needs_date():
    assert not tp.build_trip({"destination": "Dubai", "nights": 3})["ok"]


def test_build_trip_needs_nights():
    assert not tp.build_trip({"destination": "Dubai", "date": "2026-12-15"})["ok"]


def test_build_trip_nights_from_end_date():
    t = tp.build_trip({"destination": "Dubai", "date": "2026-12-15", "end": "2026-12-19"})
    assert t["nights"] == 4


def test_build_trip_city_alias():
    assert tp.build_trip({"city": "Dubai", "date": "2026-12-15", "nights": 2})["destination"] == "Dubai"


def test_build_trip_too_long():
    t = tp.build_trip({"destination": "D", "date": "2026-12-15", "nights": 99})
    assert not t["ok"]


def test_build_trip_negative_nights():
    assert not tp.build_trip({"destination": "D", "date": "2026-12-15", "nights": -3})["ok"]


def test_build_trip_bad_nights():
    assert not tp.build_trip({"destination": "D", "date": "2026-12-15", "nights": "five"})["ok"]


@pytest.mark.parametrize("pax", [0, 10])
def test_build_trip_bad_travellers(pax):
    assert not tp.build_trip({"destination": "D", "date": "2026-12-15",
                              "nights": 2, "travellers": pax})["ok"]


def test_build_trip_passengers_alias():
    assert tp.build_trip({"destination": "D", "date": "2026-12-15",
                          "nights": 2, "passengers": 3})["travellers"] == 3


def test_build_trip_bad_budget():
    assert not tp.build_trip({"destination": "D", "date": "2026-12-15",
                              "nights": 2, "budget": "lots"})["ok"]


def test_build_trip_negative_budget():
    assert not tp.build_trip({"destination": "D", "date": "2026-12-15",
                              "nights": 2, "budget": -100})["ok"]


def test_build_trip_currency_default():
    assert tp.build_trip({"destination": "D", "date": "2026-12-15",
                          "nights": 2, "currency": "dollars"})["currency"] == "USD"


def test_build_trip_style_default():
    assert tp.build_trip({"destination": "D", "date": "2026-12-15", "nights": 2})["style"] == "balanced"


def test_build_trip_style_invalid_falls_back():
    assert tp.build_trip({"destination": "D", "date": "2026-12-15",
                          "nights": 2, "style": "yolo"})["style"] == "balanced"


def test_build_trip_optional_origin(trip):
    t = tp.build_trip({"destination": "Dubai", "date": "2026-12-15", "nights": 3})
    assert t["ok"] is True and t["origin"] == ""


# ── budget ─────────────────────────────────────────────────────────────────

def test_budget_split_sums_to_total(trip):
    plan = tp.budget_split(trip)
    assert round(plan["flights"] + plan["hotel"] + plan["food"] + plan["activities"], 2) == 1500.0


def test_budget_split_per_night(trip):
    assert tp.budget_split(trip)["hotel_per_night"] == round(1500 * 0.35 / 5, 2)


def test_budget_split_budget_style(trip):
    t = dict(trip, style="budget")
    assert tp.budget_split(t)["flights"] > tp.budget_split(trip)["flights"]


def test_budget_split_comfort_style(trip):
    t = dict(trip, style="comfort")
    assert tp.budget_split(t)["hotel"] > tp.budget_split(trip)["hotel"]


def test_budget_split_zero_budget(trip):
    assert tp.budget_split(dict(trip, budget=0))["total"] == 0


def test_budget_split_unknown_style(trip):
    assert tp.budget_split(dict(trip, style="zzz"))["total"] == 1500.0


def test_cost_summary_multiplies_travellers(trip):
    costs = tp.cost_summary(trip, flight_price=400, hotel_nightly=100)
    assert costs["flights"] == 800.0 and costs["hotel"] == 500.0


def test_cost_summary_projected(trip):
    costs = tp.cost_summary(trip, 400, 100)
    assert costs["projected"] == round(800 + 500 + costs["food_activity_allowance"], 2)


def test_cost_summary_over_budget(trip):
    costs = tp.cost_summary(trip, 1000, 500)
    assert costs["over_budget"] is True and costs["remaining"] < 0


def test_cost_summary_under_budget(trip):
    costs = tp.cost_summary(trip, 200, 50)
    assert costs["over_budget"] is False and costs["remaining"] > 0


def test_cost_summary_no_budget(trip):
    costs = tp.cost_summary(dict(trip, budget=0), 400, 100)
    assert costs["over_budget"] is False and costs["remaining"] == 0


def test_cost_summary_no_prices(trip):
    assert tp.cost_summary(trip)["known"] == 0


# ── itinerary ──────────────────────────────────────────────────────────────

def test_itinerary_day_count(trip):
    days = tp.build_itinerary(trip)
    assert len(days) == 6           # 5 nights → arrival + 4 full days + departure


def test_itinerary_first_day_arrival(trip):
    assert "Arrive in Dubai" in tp.build_itinerary(trip)[0]["plan"][0]


def test_itinerary_last_day_checkout(trip):
    assert "Check out" in tp.build_itinerary(trip)[-1]["plan"][0]


def test_itinerary_dates_sequential(trip):
    days = tp.build_itinerary(trip)
    assert days[0]["date"] == "2026-12-15" and days[1]["date"] == "2026-12-16"


def test_itinerary_interests_string(trip):
    days = tp.build_itinerary(trip, "beaches, museums")
    assert any("beaches" in p for p in days[1]["plan"])


def test_itinerary_interests_list(trip):
    days = tp.build_itinerary(trip, ["food", "history"])
    assert any("food" in p for p in days[1]["plan"])


def test_itinerary_interests_rotate(trip):
    days = tp.build_itinerary(trip, ["a", "b"])
    assert any("a" in p for p in days[1]["plan"])
    assert any("b" in p for p in days[2]["plan"])


def test_itinerary_bad_date():
    assert tp.build_itinerary({"start": "nope", "nights": 3}) == []


def test_itinerary_no_start():
    assert tp.build_itinerary({"nights": 3}) == []


def test_itinerary_single_night():
    t = tp.build_trip({"destination": "D", "date": "2026-12-15", "nights": 1})
    assert len(tp.build_itinerary(t)) == 2


# ── checklist ──────────────────────────────────────────────────────────────

def test_checklist_has_passport(trip):
    assert any("Passport" in c for c in tp.checklist(trip))


def test_checklist_international_visa(trip):
    assert any("visa" in c for c in tp.checklist(trip))


def test_checklist_domestic_skips_visa(trip):
    assert not any("visa" in c for c in tp.checklist(trip, international=False))


def test_checklist_mentions_nights(trip):
    assert any("5 night" in c for c in tp.checklist(trip))


# ── render + save ──────────────────────────────────────────────────────────

def test_render_plan_sections(trip):
    text = tp.render_plan(trip, tp.build_itinerary(trip), tp.cost_summary(trip, 400, 100))
    for section in ("# Trip plan", "## Budget split", "## Found prices",
                    "## Day by day", "## Checklist"):
        assert section in text


def test_render_plan_over_budget_warning(trip):
    text = tp.render_plan(trip, [], tp.cost_summary(trip, 1000, 500))
    assert "over budget" in text


def test_render_plan_under_budget(trip):
    text = tp.render_plan(trip, [], tp.cost_summary(trip, 200, 50))
    assert "under budget" in text


def test_render_plan_includes_search_text(trip):
    text = tp.render_plan(trip, [], None, "FLIGHTS", "HOTELS")
    assert "## Flight search" in text and "HOTELS" in text


def test_render_plan_truncates_search_text(trip):
    text = tp.render_plan(trip, [], None, "x" * 5000)
    assert len(text) < 8000


def test_render_plan_no_budget_section(trip):
    assert "Found prices" not in tp.render_plan(dict(trip, budget=0), [])


def test_save_plan_writes_file(store, trip):
    path = tp.save_plan(trip, "content", now=1_800_000_000)
    assert path.exists() and path.read_text(encoding="utf-8") == "content"
    assert "trip_dubai_" in path.name


def test_save_plan_slugifies(store, trip):
    t = dict(trip, destination="New York City")
    assert "new_york_city" in tp.save_plan(t, "x").name


def test_remember_and_load_trips(store, trip):
    tp._remember_trip(trip)
    assert len(tp.load_trips()) == 1


def test_load_trips_corrupt(store):
    tp.PLAN_PATH.write_text("{bad", encoding="utf-8")
    assert tp.load_trips() == []


def test_load_trips_missing(store):
    assert tp.load_trips() == []


def test_trips_bounded(store, trip):
    for _ in range(60):
        tp._remember_trip(trip)
    assert len(tp.load_trips()) == 50


# ── dispatcher ────────────────────────────────────────────────────────────

def test_help(store):
    out = tp.trip_planner({"action": "help"})
    assert "Trip Planner" in out and "plan" in out


def test_none_params(store):
    assert isinstance(tp.trip_planner(None), str)


def test_unknown_action(store):
    assert "Unknown trip action" in tp.trip_planner({"action": "zzz"})


def test_validation_message(store):
    assert "Trip problem" in tp.trip_planner({"action": "itinerary", "destination": "Dubai"})


def test_itinerary_action(store):
    out = tp.trip_planner({"action": "itinerary", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3})
    assert "Day 1" in out and "Day 4" in out


def test_checklist_action(store):
    out = tp.trip_planner({"action": "checklist", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3})
    assert "[ ]" in out and "Passport" in out


def test_budget_action(store):
    out = tp.trip_planner({"action": "budget", "destination": "Dubai", "date": "2026-12-15",
                           "nights": 5, "budget": 1500})
    assert "Flights" in out and "Hotel" in out


def test_budget_action_with_prices(store):
    out = tp.trip_planner({"action": "budget", "destination": "Dubai", "date": "2026-12-15",
                           "nights": 5, "budget": 1500, "flight_price": 400,
                           "hotel_nightly": 100})
    assert "Projected total" in out and "to spare" in out


def test_budget_action_over(store):
    out = tp.trip_planner({"action": "budget", "destination": "Dubai", "date": "2026-12-15",
                           "nights": 5, "budget": 500, "flight_price": 900,
                           "hotel_nightly": 300})
    assert "Over budget" in out


def test_trips_action_empty(store):
    assert "No trips planned" in tp.trip_planner({"action": "trips"})


def test_trips_action_lists(store, no_search):
    tp.trip_planner({"action": "plan", "destination": "Dubai", "date": "2026-12-15",
                     "nights": 3})
    assert "Dubai" in tp.trip_planner({"action": "trips"})


def test_plan_action(store, no_search):
    out = tp.trip_planner({"action": "plan", "destination": "Dubai", "origin": "Nairobi",
                           "date": "2026-12-15", "nights": 5, "budget": 1500})
    assert "# Trip plan" in out and "Found prices" in out


def test_plan_records_trip(store, no_search):
    tp.trip_planner({"action": "plan", "destination": "Dubai", "date": "2026-12-15",
                     "nights": 3})
    assert len(tp.load_trips()) == 1


def test_plan_without_origin_skips_flights(store, no_search):
    out = tp.trip_planner({"action": "plan", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3})
    assert "Flight search" not in out


def test_plan_no_search_flag(store):
    out = tp.trip_planner({"action": "plan", "destination": "Dubai", "date": "2026-12-15",
                           "nights": 3, "no_search": True})
    assert "# Trip plan" in out


def test_plan_survives_flight_failure(store, monkeypatch):
    from actions import flight_manager as fm, hotel_manager as hm
    monkeypatch.setattr(fm, "flight_manager",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("flights down")))
    monkeypatch.setattr(hm, "hotel_manager", lambda *a, **k: "hotels ok")
    monkeypatch.setattr(fm, "op_search_site", lambda *a, **k: [])
    monkeypatch.setattr(hm, "op_search_site", lambda *a, **k: [])
    out = tp.trip_planner({"action": "plan", "destination": "Dubai", "origin": "Nairobi",
                           "date": "2026-12-15", "nights": 3})
    assert "# Trip plan" in out


def test_plan_survives_hotel_failure(store, monkeypatch):
    from actions import flight_manager as fm, hotel_manager as hm
    monkeypatch.setattr(fm, "flight_manager", lambda *a, **k: "flights ok")
    monkeypatch.setattr(hm, "hotel_manager",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("hotels down")))
    monkeypatch.setattr(fm, "op_search_site", lambda *a, **k: [])
    monkeypatch.setattr(hm, "op_search_site", lambda *a, **k: [])
    out = tp.trip_planner({"action": "plan", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3})
    assert "# Trip plan" in out


def test_save_action(store):
    out = tp.trip_planner({"action": "save", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3})
    assert "Saved:" in out and list(tp.REPORT_DIR.glob("trip_*.md"))


def test_export_notion(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.notion_agent")
    mod.create_page = lambda title, content, parent_id="": "Page created"
    monkeypatch.setitem(sys.modules, "actions.notion_agent", mod)
    out = tp.trip_planner({"action": "export", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3, "to": "notion"})
    assert "Notion: Page created" in out


def test_export_notion_failure_is_soft(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.notion_agent")
    def boom(**kw):
        raise RuntimeError("no token")
    mod.create_page = boom
    monkeypatch.setitem(sys.modules, "actions.notion_agent", mod)
    out = tp.trip_planner({"action": "export", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3, "to": "notion"})
    assert "unavailable" in out and "Saved:" in out


def test_export_docs(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.docs_agent")
    mod.docs_agent = lambda params: "Doc created"
    monkeypatch.setitem(sys.modules, "actions.docs_agent", mod)
    out = tp.trip_planner({"action": "export", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 3, "to": "docs"})
    assert "Docs: Doc created" in out


def test_dispatcher_is_crash_proof(store, monkeypatch):
    monkeypatch.setattr(tp, "build_trip",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("internal")))
    out = tp.trip_planner({"action": "itinerary", "destination": "D"})
    assert "problem" in out and "session is still running" in out


# ── honesty: never claim "under budget" when nothing was priced ────────────

def test_no_prices_is_not_under_budget(trip):
    costs = tp.cost_summary(trip)
    assert costs["has_prices"] is False and costs["complete"] is False
    assert costs["over_budget"] is False


def test_partial_prices_not_complete(trip):
    costs = tp.cost_summary(trip, flight_price=400)
    assert costs["has_prices"] is True and costs["complete"] is False


def test_full_prices_complete(trip):
    costs = tp.cost_summary(trip, 400, 100)
    assert costs["complete"] is True


def test_render_no_prices_warns_instead_of_claiming_savings(trip):
    text = tp.render_plan(trip, [], tp.cost_summary(trip))
    assert "No prices could be read" in text
    assert "under budget" not in text
    assert "not found" in text


def test_render_partial_prices_is_lower_bound(trip):
    text = tp.render_plan(trip, [], tp.cost_summary(trip, flight_price=400))
    assert "Partial total (incomplete)" in text
    assert "lower bound" in text
    assert "under budget" not in text


def test_render_full_prices_can_claim_savings(trip):
    text = tp.render_plan(trip, [], tp.cost_summary(trip, 200, 50))
    assert "under budget" in text and "Projected total" in text


def test_budget_action_no_prices_is_honest(store):
    out = tp.trip_planner({"action": "budget", "destination": "Dubai",
                           "date": "2026-12-15", "nights": 5, "budget": 1500})
    assert "nothing to compare" in out
    assert "to spare" not in out


def test_budget_action_partial_is_honest(store):
    out = tp.trip_planner({"action": "budget", "destination": "Dubai", "date": "2026-12-15",
                           "nights": 5, "budget": 1500, "flight_price": 400})
    assert "lower bound" in out and "to spare" not in out


def test_plan_without_prices_warns(store, monkeypatch):
    from actions import flight_manager as fm, hotel_manager as hm
    monkeypatch.setattr(fm, "flight_manager", lambda *a, **k: "")
    monkeypatch.setattr(hm, "hotel_manager", lambda *a, **k: "")
    monkeypatch.setattr(fm, "op_search_site", lambda *a, **k: [])
    monkeypatch.setattr(hm, "op_search_site", lambda *a, **k: [])
    out = tp.trip_planner({"action": "save", "destination": "Dubai", "origin": "Nairobi",
                           "date": "2026-12-15", "nights": 5, "budget": 1500})
    assert "No prices could be read" in out
    assert "under budget" not in out
