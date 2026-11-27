"""
Offline tests for the Daily Productivity Pack: notes, system, briefing.

No network / browser / real hardware required. psutil is faked; briefing
section providers are mocked. Run:
  python -m pytest -q tests/test_productivity_pack.py
"""

import types

import pytest

from actions import notes_agent as na
from actions import system_agent as sa
from actions import briefing_agent as ba


# ════════════════════════════════════════════════════════════════
# Notes
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def notesdb(tmp_path, monkeypatch):
    monkeypatch.setattr(na, "DB_PATH", tmp_path / "notes.db")
    monkeypatch.setattr(na, "_FTS_OK", None)
    return na


def test_add_and_search(notesdb):
    nid = notesdb.add_note("Buy oat milk and coffee beans", title="Shopping", tags="home")
    assert nid > 0
    hits = notesdb.search_notes("coffee")
    assert hits and hits[0]["id"] == nid


def test_list_and_get(notesdb):
    notesdb.add_note("first note")
    notesdb.add_note("second note")
    assert len(notesdb.list_notes()) == 2
    nid = notesdb.add_note("third note", title="T")
    assert notesdb.get_note(nid)["title"] == "T"


def test_update_and_delete(notesdb):
    nid = notesdb.add_note("original")
    assert notesdb.update_note(nid, text="changed") is True
    assert notesdb.get_note(nid)["text"] == "changed"
    assert notesdb.delete_note(nid) is True
    assert notesdb.get_note(nid) is None


def test_add_empty_returns_zero(notesdb):
    assert notesdb.add_note("   ") == 0


def test_search_weird_query_no_crash(notesdb):
    notesdb.add_note("a note about cats")
    assert isinstance(notesdb.search_notes('cats AND OR "*( '), list)


def test_format_notes(notesdb):
    assert "No notes" in notesdb.format_notes([])
    out = notesdb.format_notes([{"id": 1, "title": "T", "text": "x" * 300, "tags": "a"}])
    assert "#1" in out and "…" in out


def test_notes_agent_routing(notesdb):
    assert "saved" in notesdb.notes_agent({"action": "add", "text": "hello"})
    assert "hello" in notesdb.notes_agent({"action": "search", "query": "hello"})
    assert "Unknown notes action" in notesdb.notes_agent({"action": "bogus"})
    assert "note down" in notesdb.notes_agent({"action": "add"})


# ════════════════════════════════════════════════════════════════
# System (psutil faked)
# ════════════════════════════════════════════════════════════════

class _FakeVM:
    percent, used, total = 42.0, 8 * 1024**3, 16 * 1024**3


class _FakeDisk:
    percent, free, total = 60.0, 100 * 1024**3, 500 * 1024**3


class _FakeBattery:
    percent, power_plugged = 87.0, True


class _FakeProc:
    def __init__(self, pid, name, cpu, mem):
        self.info = {"pid": pid, "name": name, "cpu_percent": cpu, "memory_percent": mem}


class _FakePsutil:
    @staticmethod
    def cpu_percent(interval=0): return 23.0
    @staticmethod
    def cpu_count(): return 12
    @staticmethod
    def virtual_memory(): return _FakeVM()
    @staticmethod
    def disk_usage(path): return _FakeDisk()
    @staticmethod
    def sensors_battery(): return _FakeBattery()
    @staticmethod
    def boot_time(): return 0.0
    @staticmethod
    def net_io_counters(): return types.SimpleNamespace(bytes_sent=1024, bytes_recv=2048)
    @staticmethod
    def process_iter(attrs):
        return [_FakeProc(1, "chrome", 30.0, 5.0), _FakeProc(2, "code", 10.0, 8.0)]


@pytest.fixture
def fakeps(monkeypatch):
    monkeypatch.setattr(sa, "psutil", _FakePsutil())
    return sa


def test_format_bytes():
    assert sa.format_bytes(0) == "0 B"
    assert sa.format_bytes(1536) == "1.5 KB"
    assert sa.format_bytes(5 * 1024**3) == "5.0 GB"


def test_format_uptime():
    assert sa.format_uptime(90061) == "1d 1h 1m"


def test_format_overview(fakeps):
    out = sa.format_overview(sa.gather_overview())
    assert "CPU:" in out and "RAM:" in out and "Battery:" in out


def test_gather_overview(fakeps):
    d = sa.gather_overview()
    assert d["cpu_percent"] == 23.0
    assert d["memory"]["percent"] == 42.0
    assert d["battery"]["percent"] == 87.0


def test_top_processes_sorted(fakeps):
    procs = sa.top_processes(5, "cpu")
    assert procs[0]["name"] == "chrome"  # highest cpu
    procs_mem = sa.top_processes(5, "memory")
    assert procs_mem[0]["name"] == "code"  # highest mem


def test_system_agent_actions(fakeps):
    assert "SYSTEM STATUS" in sa.system_agent({"action": "status"})
    assert "CPU:" in sa.system_agent({"action": "cpu"})
    assert "RAM:" in sa.system_agent({"action": "memory"})
    assert "Battery:" in sa.system_agent({"action": "battery"})
    assert "Top processes" in sa.system_agent({"action": "processes"})
    assert "Unknown system action" in sa.system_agent({"action": "bogus"})


def test_system_agent_no_psutil(monkeypatch):
    monkeypatch.setattr(sa, "psutil", None)
    def boom(): raise ImportError("no psutil")
    monkeypatch.setattr(sa, "_get_psutil", boom)
    assert "psutil" in sa.system_agent({"action": "status"})


# ════════════════════════════════════════════════════════════════
# Briefing (providers mocked)
# ════════════════════════════════════════════════════════════════

def test_greeting_section():
    out = ba.greeting_section()
    assert "sir" in out and ("morning" in out or "afternoon" in out or "evening" in out)


def test_build_briefing_joins_sections():
    providers = {
        "greeting": lambda p: "Good morning, sir.",
        "weather":  lambda p: f"Weather in {p.get('city', 'Nairobi')}: sunny.",
        "news":     lambda p: "News: headline.",
    }
    out = ba.build_briefing(["greeting", "weather", "news"], {"city": "Nairobi"}, providers)
    assert "Good morning" in out and "sunny" in out and "headline" in out
    assert "\n\n" in out


def test_build_briefing_skips_failing_section():
    def boom(p): raise RuntimeError("down")
    providers = {"greeting": lambda p: "Hi.", "weather": boom, "news": lambda p: "News."}
    out = ba.build_briefing(["greeting", "weather", "news"], {}, providers)
    assert "Hi." in out and "News." in out  # weather skipped, others survive


def test_build_briefing_empty():
    assert "couldn't assemble" in ba.build_briefing(["greeting"], {}, {"greeting": lambda p: ""})


def test_briefing_agent_routes(monkeypatch):
    monkeypatch.setattr(ba, "build_briefing", lambda sections, params, providers=None: "BRIEFING-TEXT")
    spoken = []
    out = ba.briefing_agent({"action": "morning"}, player=None, speak=spoken.append)
    assert out == "BRIEFING-TEXT"
    assert spoken  # something was spoken


def test_briefing_agent_bad_action():
    assert "brief me" in ba.briefing_agent({"action": "bogus"})


def test_briefing_sections_string_parsed(monkeypatch):
    seen = {}
    monkeypatch.setattr(ba, "build_briefing",
                        lambda sections, params, providers=None: seen.update(sections=sections) or "X")
    ba.briefing_agent({"action": "brief", "sections": "greeting, weather"})
    assert seen["sections"] == ["greeting", "weather"]
