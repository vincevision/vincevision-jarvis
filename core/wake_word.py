"""
Wake-word detection + barge-in for JARVIS
──────────────────────────────────────────
Two independent capabilities:

1. **Wake word** — recognise "Jarvis" / "hey Jarvis" (fuzzy, so "jervis" or
   "jarviz" still work) in a transcript and strip it, leaving the command.
   Matching is pure text, so it works with any speech-to-text backend.

2. **Barge-in** — let the user interrupt JARVIS mid-sentence. This is
   energy-based (RMS), so it needs no STT at all: sustained speech above a
   threshold while JARVIS is talking triggers an interrupt. An echo guard
   ignores the first moments of playback, and a cooldown prevents flapping.

Audio capture is optional and lazily imported. Without `sounddevice` the
module still provides barge-in gating for whatever audio pipeline you already
have, and all text matching keeps working.

Config: config/wake_word.json (see config/wake_word.example.json)
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

CONFIG_PATH = Path("config") / "wake_word.json"

DEFAULT_ALIASES = ("jarvis", "hey jarvis", "ok jarvis", "yo jarvis", "hi jarvis")
DEFAULT_THRESHOLD = 0.02        # RMS, roughly normal speech on a laptop mic
DEFAULT_MIN_MS = 250            # sustained speech needed to interrupt
DEFAULT_COOLDOWN_S = 1.5
DEFAULT_ECHO_GUARD_MS = 400     # ignore our own playback onset
DEFAULT_FUZZY = 0.82


# ── Config ──────────────────────────────────────────────────────────────────

def load_config(path=None) -> dict:
    cfg = {
        "enabled": True,
        "aliases": list(DEFAULT_ALIASES),
        "fuzzy_threshold": DEFAULT_FUZZY,
        "barge_in": True,
        "rms_threshold": DEFAULT_THRESHOLD,
        "min_speech_ms": DEFAULT_MIN_MS,
        "cooldown_s": DEFAULT_COOLDOWN_S,
        "echo_guard_ms": DEFAULT_ECHO_GUARD_MS,
    }
    p = Path(path) if path else CONFIG_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cfg})
    except Exception:
        pass
    env = os.environ.get("JARVIS_WAKE_WORD")
    if env is not None:
        cfg["enabled"] = env.strip().lower() in ("1", "true", "yes", "on")
    return cfg


# ── Pure text matching ──────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    s = str(text or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


# Words that may legitimately precede the wake phrase. Anything else at the
# front means the wake word is being *mentioned*, not spoken to JARVIS
# ("the jarvis project is nice" must NOT trigger).
_FILLERS = {"um", "uh", "erm", "so", "well", "okay", "ok", "hey", "yo", "hi",
            "hello", "please", "and", "now"}


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (short strings only — wake phrases)."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _phrase_matches(phrase: str, alias: str, threshold: float) -> bool:
    """Exact, fuzzy-ratio, or a single-character slip on a long enough word.

    threshold >= 0.99 means strict mode: exact match only.
    """
    if phrase == alias:
        return True
    if threshold >= 0.99:
        return False
    if _similar(phrase, alias) >= threshold:
        return True
    # 'jarvez' / 'jarviss' should still wake it, but only for real-length names.
    if min(len(phrase), len(alias)) >= 5 and _edit_distance(phrase, alias) <= 1:
        return True
    return False


def wake_names(aliases=None) -> list[str]:
    """The distinctive word of each alias ('hey jarvis' -> 'jarvis').

    Matching anchors on the name, with an optional recognised greeting in
    front. Fuzzy-matching whole multi-word phrases against arbitrary text
    produced false positives ('the jarvis project' ~ 'hi jarvis').
    """
    aliases = aliases or DEFAULT_ALIASES
    names, seen = [], set()
    for alias in aliases:
        parts = normalize(alias).split()
        if parts and parts[-1] not in seen:
            seen.add(parts[-1])
            names.append(parts[-1])
    return names


def _starts(words: list[str]):
    """Candidate offsets: 0, then past up to two recognised filler words.

    'um hey jarvis ...' is a real utterance; 'the jarvis project' is not an
    address to JARVIS, so arbitrary leading words are not skipped.
    """
    yield 0
    i = 0
    while i < len(words) and i < 2 and words[i] in _FILLERS:
        i += 1
        yield i


def matches_wake_word(text: str, aliases=None, threshold: float = DEFAULT_FUZZY) -> bool:
    """True if the transcript *starts with* (or is) a wake phrase."""
    norm = normalize(text)
    if not norm:
        return False
    words = norm.split()
    names = wake_names(aliases)
    for start in _starts(words):
        if start >= len(words):
            continue
        for name in names:
            if _phrase_matches(words[start], name, threshold):
                return True
    return False


def extract_command(text: str, aliases=None, threshold: float = DEFAULT_FUZZY) -> str:
    """Return the transcript with the leading wake phrase removed.

    'hey jarvis open the browser' -> 'open the browser'
    If no wake phrase is present the normalised text is returned unchanged.
    """
    norm = normalize(text)
    if not norm:
        return ""
    words = norm.split()
    names = wake_names(aliases)
    best = None
    for start in _starts(words):
        if start >= len(words):
            continue
        if any(_phrase_matches(words[start], name, threshold) for name in names):
            consumed = start + 1
            if best is None or consumed > best:
                best = consumed
    if best is None:
        return norm
    return " ".join(words[best:]).strip()


# ── Audio energy ────────────────────────────────────────────────────────────

def compute_rms(samples) -> float:
    """Root-mean-square of an iterable of numeric samples (no numpy needed)."""
    total, count = 0.0, 0
    for s in samples or ():
        try:
            v = float(s)
        except (TypeError, ValueError):
            continue
        total += v * v
        count += 1
    if not count:
        return 0.0
    return math.sqrt(total / count)


def flatten_frames(indata) -> list:
    """Normalise a mic buffer to a flat list of samples.

    Handles numpy arrays (via tolist), lists of per-channel rows, and plain
    flat sequences — so the same path works with or without numpy installed.
    """
    if indata is None:
        return []
    tolist = getattr(indata, "tolist", None)
    if callable(tolist):
        indata = tolist()
    out = []
    for row in indata:
        if isinstance(row, (list, tuple)):
            out.append(row[0] if row else 0.0)
        else:
            out.append(row)
    return out


class BargeInGate:
    """Decides when the user's voice should cut JARVIS off.

    Feed it RMS values with timestamps; it returns True exactly when playback
    should stop. Pure logic — no audio device required.
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD,
                 min_speech_ms: int = DEFAULT_MIN_MS,
                 cooldown_s: float = DEFAULT_COOLDOWN_S,
                 echo_guard_ms: int = DEFAULT_ECHO_GUARD_MS):
        self.threshold = float(threshold)
        self.min_speech_ms = int(min_speech_ms)
        self.cooldown_s = float(cooldown_s)
        self.echo_guard_ms = int(echo_guard_ms)
        self.speaking = False
        self._speech_start = 0.0
        self._streak_start = None
        self._last_interrupt = 0.0
        self.interrupts = 0

    def start_speaking(self, now: float | None = None):
        self.speaking = True
        self._speech_start = time.time() if now is None else now
        self._streak_start = None

    def stop_speaking(self, now: float | None = None):
        self.speaking = False
        self._streak_start = None

    def feed(self, rms: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if not self.speaking:
            self._streak_start = None
            return False
        if (now - self._speech_start) * 1000 < self.echo_guard_ms:
            self._streak_start = None
            return False
        if rms < self.threshold:
            self._streak_start = None
            return False
        if self._streak_start is None:
            self._streak_start = now
            return False
        if (now - self._streak_start) * 1000 < self.min_speech_ms:
            return False
        if now - self._last_interrupt < self.cooldown_s:
            return False
        self._last_interrupt = now
        self._streak_start = None
        self.interrupts += 1
        return True

    def reset(self):
        self.speaking = False
        self._streak_start = None
        self._last_interrupt = 0.0
        self.interrupts = 0


# ── Engine (optional live audio) ────────────────────────────────────────────

def audio_available() -> bool:
    if os.environ.get("JARVIS_NO_AUDIO"):
        return False
    try:
        import sounddevice  # noqa: F401
        return True
    except Exception:
        return False


class WakeWordEngine:
    """Wires barge-in (and optional transcript wake-word) to a live mic.

    `transcribe` is an optional callable(bytes_or_frames) -> str. When given,
    recognised transcripts are checked for the wake phrase and `on_wake` is
    called with the extracted command. Without it, barge-in still works.
    """

    def __init__(self, config: dict | None = None, transcribe=None,
                 clock=time.time, stream_factory=None):
        self.config = config or load_config()
        self.transcribe = transcribe
        self._clock = clock
        self._stream_factory = stream_factory
        self.gate = BargeInGate(
            threshold=self.config.get("rms_threshold", DEFAULT_THRESHOLD),
            min_speech_ms=self.config.get("min_speech_ms", DEFAULT_MIN_MS),
            cooldown_s=self.config.get("cooldown_s", DEFAULT_COOLDOWN_S),
            echo_guard_ms=self.config.get("echo_guard_ms", DEFAULT_ECHO_GUARD_MS),
        )
        self.on_wake = None
        self.on_interrupt = None
        self._stream = None
        self.running = False

    # Playback hooks — call these from the TTS layer.
    def speech_started(self):
        self.gate.start_speaking(self._clock())

    def speech_finished(self):
        self.gate.stop_speaking(self._clock())

    def handle_transcript(self, text: str) -> str | None:
        """Return the command if the transcript contains the wake word."""
        if not self.config.get("enabled", True):
            return None
        if not matches_wake_word(text, self.config.get("aliases"),
                                 self.config.get("fuzzy_threshold", DEFAULT_FUZZY)):
            return None
        command = extract_command(text, self.config.get("aliases"),
                                  self.config.get("fuzzy_threshold", DEFAULT_FUZZY))
        if self.on_wake:
            try:
                self.on_wake(command)
            except Exception:
                pass
        return command

    def handle_audio(self, samples) -> bool:
        """Feed one audio frame; True means 'stop speaking now'."""
        if not self.config.get("barge_in", True):
            return False
        rms = compute_rms(samples)
        if self.gate.feed(rms, self._clock()):
            if self.on_interrupt:
                try:
                    self.on_interrupt()
                except Exception:
                    pass
            return True
        return False

    def _make_stream(self, callback):
        if self._stream_factory:
            return self._stream_factory(callback)
        import sounddevice as sd
        return sd.InputStream(channels=1, samplerate=16000, blocksize=1600,
                              callback=callback)

    def start(self, on_wake=None, on_interrupt=None) -> str:
        if self.running:
            return "Wake-word engine already running."
        if not self.config.get("enabled", True):
            return "Wake word is disabled in config/wake_word.json."
        self.on_wake = on_wake
        self.on_interrupt = on_interrupt

        def _callback(indata, frames, time_info, status):
            try:
                self.handle_audio(flatten_frames(indata))
            except Exception:
                pass

        try:
            self._stream = self._make_stream(_callback)
            self._stream.start()
        except Exception as e:
            return f"Microphone unavailable ({e}). Barge-in gating still works if you feed it audio."
        self.running = True
        return "🎙️ Wake word active — say 'Jarvis'. Barge-in enabled."

    def stop(self) -> str:
        self.running = False
        try:
            if self._stream is not None:
                self._stream.stop()
                close = getattr(self._stream, "close", None)
                if close:
                    close()
        except Exception:
            pass
        self._stream = None
        self.gate.reset()
        return "🎙️ Wake word stopped."

    def status(self) -> str:
        mode = "listening" if self.running else "idle"
        return (f"Wake word: {'enabled' if self.config.get('enabled', True) else 'disabled'} ({mode})\n"
                f"  Aliases: {', '.join(self.config.get('aliases', DEFAULT_ALIASES))}\n"
                f"  Barge-in: {'on' if self.config.get('barge_in', True) else 'off'} "
                f"(RMS ≥ {self.config.get('rms_threshold')}, "
                f"{self.config.get('min_speech_ms')} ms)\n"
                f"  Microphone: {'available' if audio_available() else 'not available'}\n"
                f"  Interrupts so far: {self.gate.interrupts}")


# ── Tool entry point ────────────────────────────────────────────────────────

_engine: WakeWordEngine | None = None


def get_engine() -> WakeWordEngine:
    global _engine
    if _engine is None:
        _engine = WakeWordEngine()
    return _engine


def wake_word_control(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    engine = get_engine()
    try:
        if action in ("start", "enable", "on"):
            return engine.start()
        if action in ("stop", "disable", "off"):
            return engine.stop()
        if action == "status":
            return engine.status()
        if action in ("test", "match"):
            text = params.get("text", "")
            if not text:
                return "Give me some text to test against the wake word."
            cmd = engine.handle_transcript(text)
            if cmd is None:
                return f"No wake word detected in: {text}"
            return f"✅ Wake word detected. Command: '{cmd}'" if cmd else "✅ Wake word detected (no command followed)."
        if action == "config":
            return json.dumps(engine.config, indent=2)
        return f"Unknown wake-word action '{action}'. Try start, stop, status, test."
    except Exception as e:
        return f"wake_word_control '{action}' failed: {e}"
