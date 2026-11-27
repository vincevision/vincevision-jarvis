"""
calendar_agent.py — VINCEVISION Google Calendar
────────────────────────────────────────────────
Voice-driven scheduling on the official Calendar API.

Actions: today / upcoming / list / create / delete / setup / status
Times: ISO 8601 ("2026-11-28T15:00:00") or date-only for all-day events.
Default timezone: Africa/Nairobi (override with `timezone`).
"""

from datetime import datetime, timedelta, timezone

from actions import google_auth

DEFAULT_TIMEZONE = "Africa/Nairobi"
DEFAULT_CALENDAR = "primary"


def _service():
    return google_auth.get_service("calendar", "v3")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def parse_when(value: str, duration_minutes: int = 60):
    """Return (start_dict, end_dict) for the Calendar API from user input.

    Accepts ISO datetimes, 'YYYY-MM-DD' (all-day), or 'YYYY-MM-DD HH:MM'.
    Returns None if unparseable.
    """
    v = (value or "").strip()
    if not v:
        return None
    try:
        if len(v) == 10:  # date-only → all-day event
            day = datetime.strptime(v, "%Y-%m-%d").date()
            nxt = day + timedelta(days=1)
            return {"date": day.isoformat()}, {"date": nxt.isoformat()}
        v2 = v.replace(" ", "T", 1) if " " in v and "T" not in v else v
        dt = datetime.fromisoformat(v2)
        end = dt + timedelta(minutes=max(1, duration_minutes))
        return {"dateTime": _rfc3339(dt)}, {"dateTime": _rfc3339(end)}
    except Exception:
        return None


def format_event(ev: dict) -> str:
    start = ev.get("start", {})
    when = start.get("dateTime", start.get("date", "?"))
    if "T" in when:
        when = when[:16].replace("T", " ")
    title = ev.get("summary", "(no title)")
    loc = ev.get("location", "")
    line = f"  • {when} — {title}"
    if loc:
        line += f" @ {loc}"
    return line


def create_event(summary: str, start: str, end: str = "", description: str = "",
                 location: str = "", calendar_id: str = DEFAULT_CALENDAR,
                 timezone_name: str = DEFAULT_TIMEZONE,
                 duration_minutes: int = 60) -> str:
    service = _service()
    parsed = parse_when(start, duration_minutes)
    if not parsed:
        return ("I couldn't parse that start time, sir. "
                "Use ISO like 2026-11-28T15:00 or a date like 2026-11-28.")
    start_d, end_d = parsed
    if end:
        parsed_end = parse_when(end, duration_minutes)
        if parsed_end:
            end_d = parsed_end[0]  # explicit end value, not end+duration
    if "dateTime" in start_d:
        start_d["timeZone"] = timezone_name
        end_d["timeZone"] = timezone_name
    body = {"summary": summary or "New event", "start": start_d, "end": end_d}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    ev = service.events().insert(calendarId=calendar_id, body=body).execute()
    link = ev.get("htmlLink", "")
    return f"✅ Event '{body['summary']}' created." + (f" {link}" if link else "")


def list_events(time_min: str = "", time_max: str = "", limit: int = 10,
                calendar_id: str = DEFAULT_CALENDAR) -> str:
    service = _service()
    kwargs = {"calendarId": calendar_id, "singleEvents": True,
              "orderBy": "startTime", "maxResults": max(1, limit)}
    kwargs["timeMin"] = time_min or _now_iso()
    if time_max:
        kwargs["timeMax"] = time_max
    res = service.events().list(**kwargs).execute()
    items = res.get("items", [])
    if not items:
        return "No events in that window, sir."
    return "\n".join(format_event(e) for e in items)


def calendar_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "today")).lower().strip()

    if action in ("setup", "help", "connect"):
        return google_auth.setup_instructions()
    if action == "status":
        return google_auth.status()

    try:
        if action in ("today", "agenda"):
            now = datetime.now(timezone.utc)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            out = list_events(_rfc3339(start), _rfc3339(end),
                              limit=int(params.get("limit", 20)))
            if speak:
                speak("Here's your agenda for today, sir." if "•" in out
                      else "Your calendar is clear today, sir.")
            return "📅 TODAY\n" + out

        if action in ("upcoming", "list", "week"):
            days = int(params.get("days", 7))
            now = datetime.now(timezone.utc)
            out = list_events(_rfc3339(now), _rfc3339(now + timedelta(days=days)),
                              limit=int(params.get("limit", 20)))
            return f"📅 NEXT {days} DAYS\n" + out

        if action in ("create", "add", "schedule", "book"):
            summary = params.get("summary") or params.get("title") or ""
            start = params.get("start") or params.get("when") or ""
            if not summary or not start:
                return "I need a title and a start time to schedule that, sir."
            return create_event(
                summary, start, params.get("end", ""),
                params.get("description", ""), params.get("location", ""),
                calendar_id=params.get("calendar_id", DEFAULT_CALENDAR),
                timezone_name=params.get("timezone", DEFAULT_TIMEZONE),
                duration_minutes=int(params.get("duration_minutes", 60)))

        if action in ("delete", "remove", "cancel"):
            eid = params.get("id") or params.get("event_id")
            if not eid:
                return "Which event id should I delete, sir?"
            service = _service()
            service.events().delete(
                calendarId=params.get("calendar_id", DEFAULT_CALENDAR),
                eventId=eid).execute()
            return f"✅ Event {eid} deleted."

        return "Calendar actions: today, upcoming, create, delete, setup."
    except Exception as e:
        return f"Calendar request failed: {e}"
