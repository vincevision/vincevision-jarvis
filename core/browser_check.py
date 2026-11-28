"""
Chromium presence check — shared by doctor.py and core/env_setup.py
──────────────────────────────────────────────────────────────────
The old check asked "does ~/.cache/ms-playwright exist and is it non-empty?".
That reports ✅ even when the browser download FAILED, because the cache can
hold a partial download, an unrelated browser, or just a `.links` folder.

This module looks for an actual Chromium **executable** instead, so a failed
`playwright install chromium` is reported honestly.

Stdlib only. Never raises. Nothing here downloads or launches anything.

Layout note: Playwright's on-disk layout has changed across releases (Chrome
for Testing moved from `chrome-linux/chrome` to `chrome-linux64/chrome`), so
several known patterns are matched rather than one hardcoded path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Relative to a playwright browser-cache root.
_CHROMIUM_PATTERNS = (
    "chromium-*/chrome-linux/chrome",
    "chromium-*/chrome-linux64/chrome",
    "chromium-*/chrome-win/chrome.exe",
    "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    "chromium-*/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
    "chromium-*/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
)

_HEADLESS_PATTERNS = (
    "chromium_headless_shell-*/chrome-linux/headless_shell",
    "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    "chromium_headless_shell-*/chrome-win/headless_shell.exe",
    "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
)


def install_command(with_deps: bool = False) -> list[str]:
    """The install command to recommend/run.

    Uses `python -m playwright` rather than the bare `playwright` script: the
    module form always uses *this* interpreter's package, so a stray global
    `playwright` on PATH (Node or another venv) can't shadow it.
    """
    cmd = [sys.executable or "python", "-m", "playwright", "install"]
    if with_deps:
        cmd.append("--with-deps")
    cmd.append("chromium")
    return cmd


def install_hint(with_deps: bool = False) -> str:
    cmd = install_command(with_deps)
    shown = ["python"] + cmd[1:]
    return " ".join(shown)


def cache_candidates(home: Path | None = None) -> list[Path]:
    """Possible Playwright cache roots, most likely first (no filesystem scan)."""
    out: list[Path] = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env not in ("0",):
        out.append(Path(env))
    h = Path(home) if home else Path.home()
    out.append(h / ".cache" / "ms-playwright")
    if sys.platform == "darwin":
        out.append(h / "Library" / "Caches" / "ms-playwright")
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            out.append(Path(local) / "ms-playwright")
    # De-duplicate, preserving order.
    seen, uniq = set(), []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def find_chromium(cache=None, patterns=None) -> Path | None:
    """Return the first real Chromium executable under `cache`, else None."""
    root = Path(cache) if cache else None
    roots = [root] if root else cache_candidates()
    pats = tuple(patterns) if patterns else _CHROMIUM_PATTERNS
    for base in roots:
        try:
            if not base.is_dir():
                continue
            for pattern in pats:
                for hit in sorted(base.glob(pattern)):
                    try:
                        if hit.is_file():
                            return hit
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def find_headless_shell(cache=None) -> Path | None:
    return find_chromium(cache, patterns=_HEADLESS_PATTERNS)


def cache_has_content(cache=None) -> bool:
    """True if a cache dir exists and holds anything (the OLD, weak check)."""
    roots = [Path(cache)] if cache else cache_candidates()
    for base in roots:
        try:
            if base.is_dir() and any(base.iterdir()):
                return True
        except OSError:
            continue
    return False


def chromium_status(cache=None) -> dict:
    """Honest browser status.

    installed   — a Chromium executable was found
    cache       — the cache root that was inspected (or None)
    executable  — full path to the binary (or "")
    stale_cache — a non-empty cache exists but holds no Chromium: this is the
                  "install failed but the folder is there" case
    """
    exe = find_chromium(cache)
    roots = [Path(cache)] if cache else cache_candidates()
    existing = next((p for p in roots if _is_dir(p)), None)
    return {
        "installed": exe is not None,
        "executable": str(exe) if exe else "",
        "cache": str(existing) if existing else "",
        "stale_cache": exe is None and cache_has_content(cache),
        "headless_shell": bool(find_headless_shell(cache)),
        "hint": install_hint(),
    }


def _is_dir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:
        return False


def describe(status: dict | None = None) -> str:
    st = status or chromium_status()
    if st["installed"]:
        return f"Chromium ready at {st['executable']}"
    if st["stale_cache"]:
        return (f"Browser cache {st['cache']} exists but contains no Chromium — "
                f"the download did not complete.")
    return "Chromium is not installed."
