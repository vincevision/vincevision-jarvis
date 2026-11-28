"""
Trip Planner for JARVIS — flights + stays + a day-by-day plan, on screen
────────────────────────────────────────────────────────────────────────
    "Plan a trip to Dubai, Dec 15 for 5 nights, budget 1500"

It runs the flight and hotel searches **visibly** (you watch the sites open),
builds a budget, writes a day-by-day itinerary, and can push the plan to
Google Docs / Notion or save it to reports/.

  plan       — full trip: flights + hotels + budget + itinerary
  itinerary  — day-by-day plan only (no searching, instant)
  budget     — cost breakdown for a trip
  checklist  — pre-trip checklist (visa, insurance, packing, check-in)
  save       — write the plan to reports/ (and optionally Docs/Notion)
  status     — what's configured

Every step is narrated through core/visible.py and the dispatcher is wrapped
in core/safe_run.safe_tool, so a failing site never crashes the session.

Safety
──────
Searching is delegated to flight_manager / hotel_manager, which open a visible
browser. This module never books, never pays, and never enters payment details
or card data — you complete any purchase yourself.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from core.safe_run import guard, safe_tool
from core.visible import Narrator

REPORT_DIR = Path("reports")
PLAN_PATH = Path("memory") / "trips.json"
MAX_TRIP_DAYS = 30


def _flights():
    from actions import flight_manager
    return flight_manager


def _hotels():
    from actions import hotel_manager
    return hotel_manager


def _alerts():
    from core import alerts
    return alerts


# ── Pure helpers ────────────────────────────────────────────────────────────

def parse_date(raw, today: datetime | None = None) -> str:
    from actions.flight_manager import parse_date as fd
    return fd(raw, today)


def build_trip(params: dict, today: datetime | None = None) -> dict:
    errors = []
    destination = str(params.get("destination") or params.get("city") or "").strip()
    origin = str(params.get("origin") or "").strip()
    if not destination:
        errors.append("Where to? Give me a destination city.")

    start = parse_date(params.get("date") or params.get("start") or params.get("depart"), today)
    if not start:
        errors.append("When? Give me a start date (2026-12-15, 'next friday', 'in 3 weeks').")

    try:
        nights = int(params.get("nights", 0) or 0)
    except (TypeError, ValueError):
        nights = 0
        errors.append("nights must be a whole number.")
    if nights <= 0:
        end = parse_date(params.get("end") or params.get("return_date"), today)
        if start and end:
            try:
                nights = (datetime.strptime(end, "%Y-%m-%d")
                          - datetime.strptime(start, "%Y-%m-%d")).days
            except ValueError:
                nights = 0
    if nights <= 0:
        errors.append("How many nights? (or give an end/return date)")
    if nights > MAX_TRIP_DAYS:
        errors.append(f"Trips longer than {MAX_TRIP_DAYS} nights aren't supported here.")

    end = ""
    if start and nights > 0:
        end = (datetime.strptime(start, "%Y-%m-%d")
               + timedelta(days=nights)).strftime("%Y-%m-%d")

    try:
        travellers = int(params.get("travellers", params.get("passengers", 1)))
    except (TypeError, ValueError):
        travellers = 0
    if not 1 <= travellers <= 9:
        errors.append("travellers must be between 1 and 9.")

    try:
        budget = float(params.get("budget", 0) or 0)
    except (TypeError, ValueError):
        errors.append("budget must be a number.")
        budget = 0.0
    if budget < 0:
        errors.append("budget cannot be negative.")

    currency = str(params.get("currency", "USD")).upper().strip()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        currency = "USD"

    style = str(params.get("style", "balanced")).lower().strip()
    if style not in ("budget", "balanced", "comfort"):
        style = "balanced"

    return {"ok": not errors, "errors": errors, "origin": origin,
            "destination": destination, "start": start, "end": end,
            "nights": max(0, nights), "travellers": travellers,
            "budget": budget, "currency": currency, "style": style}


# Budget split by travel style — percentages of the total budget.
_STYLE_SPLIT = {
    "budget": {"flights": 0.45, "hotel": 0.30, "food": 0.15, "activities": 0.10},
    "balanced": {"flights": 0.40, "hotel": 0.35, "food": 0.15, "activities": 0.10},
    "comfort": {"flights": 0.35, "hotel": 0.45, "food": 0.12, "activities": 0.08},
}


def budget_split(trip: dict) -> dict:
    """Allocate a total budget across categories (amounts in trip currency)."""
    total = float(trip.get("budget", 0) or 0)
    split = _STYLE_SPLIT.get(trip.get("style", "balanced"), _STYLE_SPLIT["balanced"])
    out = {k: round(total * v, 2) for k, v in split.items()}
    nights = max(1, int(trip.get("nights", 1) or 1))
    out["hotel_per_night"] = round(out["hotel"] / nights, 2)
    out["food_per_day"] = round(out["food"] / nights, 2)
    out["total"] = round(total, 2)
    return out


def cost_summary(trip: dict, flight_price: float = 0, hotel_nightly: float = 0) -> dict:
    """Compare actual found prices against the budget."""
    nights = max(1, int(trip.get("nights", 1) or 1))
    travellers = max(1, int(trip.get("travellers", 1) or 1))
    flights_total = round(float(flight_price or 0) * travellers, 2)
    hotel_total = round(float(hotel_nightly or 0) * nights, 2)
    plan = budget_split(trip)
    known = round(flights_total + hotel_total, 2)
    allowance = round(plan["food"] + plan["activities"], 2)
    projected = round(known + allowance, 2)
    budget = float(trip.get("budget", 0) or 0)
    # Honesty: if a search found nothing, we must NOT claim "under budget".
    priced = bool(flight_price or hotel_nightly)
    complete = bool(flight_price) and bool(hotel_nightly)
    return {"flights": flights_total, "hotel": hotel_total, "known": known,
            "food_activity_allowance": allowance, "projected": projected,
            "budget": budget,
            "remaining": round(budget - projected, 2) if budget else 0.0,
            "over_budget": bool(budget and priced and projected > budget),
            "has_prices": priced, "complete": complete,
            "nights": nights, "travellers": travellers}


def build_itinerary(trip: dict, interests=None) -> list[dict]:
    """A sensible day-by-day skeleton. No invented opening hours or prices."""
    nights = max(1, int(trip.get("nights", 1) or 1))
    dest = trip.get("destination", "your destination")
    tags = interests or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,\s]+", tags) if t.strip()]
    days = []
    try:
        base = datetime.strptime(trip["start"], "%Y-%m-%d")
    except (KeyError, ValueError, TypeError):
        return []
    for i in range(nights + 1):
        date = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        if i == 0:
            plan = [f"Arrive in {dest}", "Check in and drop bags",
                    "Easy first evening — food near the stay, early night"]
        elif i == nights:
            plan = ["Check out", "Last-minute walk or souvenirs",
                    "Head to the airport with a buffer"]
        else:
            plan = [f"Morning: a headline sight in {dest}",
                    "Afternoon: neighbourhood walk / museum / market",
                    "Evening: local dinner"]
            if tags:
                plan.insert(1, f"Focus today: {tags[(i - 1) % len(tags)]}")
            if i == 1:
                plan.append("Buy a local SIM / transit card if needed")
        days.append({"day": i + 1, "date": date, "plan": plan})
    return days


def checklist(trip: dict, international: bool = True) -> list[str]:
    nights = int(trip.get("nights", 0) or 0)
    items = ["Passport valid 6+ months beyond travel",
             "Travel insurance sorted",
             "Book flights and stay, save confirmations offline",
             "Tell your bank you're travelling",
             "Check phone roaming / plan a local SIM",
             f"Pack for {nights} night(s) and the local weather",
             "Online check-in 24–48h before departure",
             "Share the itinerary with someone at home"]
    if international:
        items.insert(1, "Check visa / entry rules for your passport")
        items.insert(2, "Check any vaccination or health entry requirements")
    return items


def render_plan(trip: dict, itinerary: list[dict], costs: dict | None = None,
                flight_text: str = "", hotel_text: str = "",
                now: float | None = None) -> str:
    import time
    now = time.time() if now is None else now
    cur = trip["currency"]
    lines = [f"# Trip plan — {trip['destination']}",
             f"_{datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M')}_", "",
             f"- Dates: {trip['start']} → {trip['end']} ({trip['nights']} night(s))",
             f"- Travellers: {trip['travellers']} · Style: {trip['style']}"]
    if trip.get("origin"):
        lines.append(f"- From: {trip['origin']}")
    if trip.get("budget"):
        lines.append(f"- Budget: {cur} {trip['budget']:,.0f}")
    lines += ["", "## Budget split", ""]
    plan = budget_split(trip)
    for key in ("flights", "hotel", "food", "activities"):
        lines.append(f"- {key.title()}: {cur} {plan[key]:,.0f}")
    if plan["hotel_per_night"]:
        lines.append(f"- Hotel target: {cur} {plan['hotel_per_night']:,.0f}/night")
    if costs:
        lines += ["", "## Found prices", ""]
        if not costs.get("has_prices"):
            lines += ["> ⚠️ No prices could be read from the sites, so there is nothing",
                      "> to compare against your budget yet. The budget split above is",
                      "> a planning target, not a quote. Open the links and check, or",
                      "> install the browser dependency and search again.", ""]
        lines += [f"- Flights: "
                  + (f"{cur} {costs['flights']:,.0f} ({costs['travellers']} traveller(s))"
                     if costs["flights"] else "not found"),
                  f"- Stay: "
                  + (f"{cur} {costs['hotel']:,.0f} ({costs['nights']} night(s))"
                     if costs["hotel"] else "not found"),
                  f"- Food/activities allowance: {cur} {costs['food_activity_allowance']:,.0f}"]
        if costs.get("has_prices"):
            label = "Projected total" if costs.get("complete") else "Partial total (incomplete)"
            lines.append(f"- **{label}: {cur} {costs['projected']:,.0f}**")
        if costs["budget"] and costs.get("has_prices"):
            if costs["over_budget"]:
                lines.append(f"- ⚠️ over budget by {cur} {abs(costs['remaining']):,.0f}")
            elif costs.get("complete"):
                lines.append(f"- ✅ under budget by {cur} {costs['remaining']:,.0f}")
            else:
                lines.append("- ℹ️ some prices are missing — treat this as a lower bound")
    lines += ["", "## Day by day", ""]
    for d in itinerary:
        lines.append(f"### Day {d['day']} — {d['date']}")
        lines += [f"- {p}" for p in d["plan"]]
        lines.append("")
    lines += ["## Checklist", ""] + [f"- [ ] {c}" for c in checklist(trip)]
    if flight_text:
        lines += ["", "## Flight search", "", "```", flight_text[:2000], "```"]
    if hotel_text:
        lines += ["", "## Hotel search", "", "```", hotel_text[:2000], "```"]
    return "\n".join(lines) + "\n"


def save_plan(trip: dict, text: str, now: float | None = None) -> Path:
    import time
    now = time.time() if now is None else now
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", trip["destination"].lower()).strip("_")
    path = REPORT_DIR / f"trip_{slug}_{datetime.fromtimestamp(now).strftime('%Y%m%d_%H%M')}.md"
    path.write_text(text, encoding="utf-8")
    return path


def load_trips(path=None) -> list:
    p = Path(path) if path else PLAN_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _remember_trip(trip: dict, path=None):
    p = Path(path) if path else PLAN_PATH
    try:
        rows = load_trips(p)
        rows.append(trip)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows[-50:], indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Dispatcher ──────────────────────────────────────────────────────────────

_ACTIONS = {"help", "status", "plan", "itinerary", "budget", "checklist",
            "save", "trips", "export"}


@safe_tool("trip_planner")
def trip_planner(parameters: dict, player=None, speak=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "help")).lower().strip()
    n = Narrator(player, speak, prefix="Trip")

    if action in ("help", "status"):
        return ("🧳 Trip Planner\n"
                "  plan      — flights + hotels searched on screen, budget, day-by-day plan\n"
                "  itinerary — day-by-day only (instant, no searching)\n"
                "  budget    — cost split and projection\n"
                "  checklist — pre-trip to-dos\n"
                "  save      — write the plan to reports/\n"
                "  export    — also push to Notion / Google Docs\n"
                "Example: plan a trip to Dubai from Nairobi, Dec 15, 5 nights, budget 1500")

    if action == "trips":
        rows = load_trips()
        if not rows:
            return "No trips planned yet."
        return "🧳 Planned trips:\n" + "\n".join(
            f"  {t.get('destination')} · {t.get('start')} → {t.get('end')} "
            f"({t.get('nights')}n, {t.get('travellers')} pax)" for t in rows[-10:])

    if action not in _ACTIONS:
        return f"Unknown trip action '{action}'. Say 'trip help' for the list."

    trip = build_trip(params)
    if not trip["ok"]:
        return "Trip problem: " + "; ".join(trip["errors"])

    itinerary = build_itinerary(trip, params.get("interests"))

    if action == "itinerary":
        lines = [f" {trip['destination']} · {trip['start']} → {trip['end']}"]
        for d in itinerary:
            lines.append(f"\nDay {d['day']} ({d['date']}):")
            lines += [f"  • {p}" for p in d["plan"]]
        return "\n".join(lines)

    if action == "checklist":
        return ("✅ Pre-trip checklist:\n"
                + "\n".join(f"  [ ] {c}" for c in checklist(trip)))

    if action == "budget":
        costs = cost_summary(trip, float(params.get("flight_price", 0) or 0),
                             float(params.get("hotel_nightly", 0) or 0))
        plan = budget_split(trip)
        lines = [f"💰 Budget for {trip['destination']} ({trip['nights']}n, "
                 f"{trip['travellers']} pax, {trip['style']}):"]
        for key in ("flights", "hotel", "food", "activities"):
            lines.append(f"  {key.title()}: {trip['currency']} {plan[key]:,.0f}")
        if costs["has_prices"]:
            label = "Projected total" if costs["complete"] else "Partial total (incomplete)"
            lines.append(f"\n  {label}: {trip['currency']} {costs['projected']:,.0f}")
            if costs["budget"]:
                if costs["over_budget"]:
                    lines.append("  ⚠️ Over budget")
                elif costs["complete"]:
                    lines.append(f"  ✅ {trip['currency']} {costs['remaining']:,.0f} to spare")
                else:
                    lines.append("  ℹ️ Some prices missing — treat this as a lower bound")
        else:
            lines.append("\n  No prices supplied, so nothing to compare against the budget yet.")
        return "\n".join(lines)

    if action in ("plan", "save", "export"):
        flight_text = hotel_text = ""
        flight_price = hotel_nightly = 0.0
        do_search = action == "plan" and not params.get("no_search")

        if do_search:
            plan = budget_split(trip)
            if trip["origin"]:
                n.doing(f"Searching flights {trip['origin']} → {trip['destination']}", True)
                fm = _flights()
                flight_text = guard(
                    fm.flight_manager,
                    {"action": "compare", "origin": trip["origin"],
                     "destination": trip["destination"], "date": trip["start"],
                     "return_date": trip["end"], "passengers": trip["travellers"],
                     "currency": trip["currency"],
                     "max_price": plan["flights"] / max(1, trip["travellers"]),
                     "sites": params.get("flight_sites") or "kayak,google"},
                    default="", label="trip.flights", player=player, speak=speak) or ""
                s = guard(fm.build_search,
                          {"origin": trip["origin"], "destination": trip["destination"],
                           "date": trip["start"], "return_date": trip["end"]},
                          default=None, label="trip.flight_search")
                if s and s.get("ok"):
                    offers = guard(fm.op_search_site, "kayak", s, n, 0,
                                   default=[], label="trip.flight_price")
                    if offers:
                        flight_price = min(float(o["price"]) for o in offers)
            else:
                n.info("No origin given — skipping flights (add 'from <city>').")

            n.doing(f"Searching stays in {trip['destination']}", True)
            hm = _hotels()
            hotel_text = guard(
                hm.hotel_manager,
                {"action": "compare", "city": trip["destination"], "checkin": trip["start"],
                 "checkout": trip["end"], "guests": trip["travellers"],
                 "currency": trip["currency"], "max_price": plan["hotel_per_night"],
                 "sites": params.get("hotel_sites") or "booking,google"},
                default="", label="trip.hotels", player=player, speak=speak) or ""
            hs = guard(hm.build_search,
                       {"city": trip["destination"], "checkin": trip["start"],
                        "checkout": trip["end"], "guests": trip["travellers"]},
                       default=None, label="trip.hotel_search")
            if hs and hs.get("ok"):
                stays = guard(hm.op_search_site, "booking", hs, n, 0,
                              default=[], label="trip.hotel_price")
                if stays:
                    hotel_nightly = min(float(x["price"]) for x in stays)

        costs = cost_summary(trip, flight_price, hotel_nightly)
        text = render_plan(trip, itinerary, costs, flight_text, hotel_text)
        _remember_trip(trip)

        if action in ("save", "export") or params.get("save"):
            path = save_plan(trip, text)
            n.done(f"Plan saved to {path}")
            extra = ""
            if action == "export":
                targets = str(params.get("to") or "notion").lower()
                if "notion" in targets:
                    def _to_notion():
                        from actions.notion_agent import create_page
                        return create_page(title=f"Trip — {trip['destination']} {trip['start']}",
                                           content=text)
                    r = guard(_to_notion, default="Notion export unavailable", label="trip.notion")
                    extra += f"\n📝 Notion: {r}"
                if "docs" in targets or "doc" in targets:
                    def _to_docs():
                        from actions.docs_agent import docs_agent
                        return docs_agent({"action": "create",
                                           "title": f"Trip — {trip['destination']} {trip['start']}",
                                           "content": text})
                    r = guard(_to_docs, default="Docs export unavailable", label="trip.docs")
                    extra += f"\n📄 Docs: {r}"
            summary = (f"🧳 Trip plan ready: {trip['destination']} "
                       f"{trip['start']} → {trip['end']} ({trip['nights']}n)\n"
                       f"📄 Saved: {path}{extra}")
            if not costs["has_prices"]:
                summary += ("\n⚠️ No prices could be read from the sites — the budget split "
                            "is a target, not a quote.")
            elif costs["budget"]:
                if costs["over_budget"]:
                    summary += "\n⚠️ Projected over budget"
                elif costs["complete"]:
                    summary += (f"\n✅ Projected {trip['currency']} "
                                f"{costs['remaining']:,.0f} under budget")
                else:
                    summary += "\nℹ️ Some prices missing — the total is a lower bound"
            return summary + "\n\n" + text

        n.done("Trip plan built")
        return text

    return f"Unknown trip action '{action}'. Say 'trip help' for the list."
