"""
ai_router.py
────────────
Universal AI router with automatic fallback.
Priority: Gemini 2.5 Flash → Groq Llama → Error
"""

import json
import time
import traceback
from pathlib import Path
import sys


def _get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _load_keys() -> dict:
    """Load API keys from credential manager first, then fall back to json."""
    keys = {}
    try:
        from core.credential_manager import get_credential
        gemini = get_credential("gemini", "api_key")
        groq   = get_credential("groq",   "api_key")
        if gemini: keys["gemini_api_key"] = gemini
        if groq:   keys["groq_api_key"]   = groq
    except Exception:
        pass
    if not keys.get("gemini_api_key") or not keys.get("groq_api_key"):
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if not keys.get("gemini_api_key"):
                    keys["gemini_api_key"] = loaded.get("gemini_api_key", "")
                if not keys.get("groq_api_key"):
                    keys["groq_api_key"] = (
                        loaded.get("groq_api_key", "")
                        or loaded.get("groq_key", "")
                    )
        except Exception as e:
            print(f"[AI Router] ❌ Could not load api_keys.json: {e}")
    return keys


# ════════════════════════════════════════════════
# GEMINI CLIENT
# ════════════════════════════════════════════════

def _ask_gemini(
    prompt: str,
    system: str = "",
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    """Send a prompt to Google Gemini and return the response text."""
    from google import genai
    from google.genai import types

    keys    = _load_keys()
    api_key = keys.get("gemini_api_key", "")
    if not api_key:
        raise ValueError("No Gemini API key found.")

    client = genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1beta"}
    )

    if system:
        content_text = f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}"
    else:
        content_text = prompt

    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=content_text)]
        )
    ]

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    return response.text.strip()


# ════════════════════════════════════════════════
# GROQ CLIENT
# ════════════════════════════════════════════════

def _ask_grok(
    prompt: str,
    system: str = "",
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    """Send a prompt to Groq and return the response text."""
    from openai import OpenAI

    keys    = _load_keys()
    api_key = keys.get("groq_api_key", "")
    if not api_key:
        raise ValueError("No Groq API key found.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()


# ════════════════════════════════════════════════
# PROVIDERS LIST — order = fallback priority
# ════════════════════════════════════════════════

PROVIDERS = [
    {
        "name":   "Gemini",
        "fn":     _ask_gemini,
        "models": [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
        ],
        "key":    "gemini_api_key",
    },
    {
        "name":   "Groq",
        "fn":     _ask_grok,
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ],
        "key":    "groq_api_key",
    },
]


# ════════════════════════════════════════════════
# UNIVERSAL ROUTER
# ════════════════════════════════════════════════

def ask_ai(
    prompt: str,
    system: str = "",
    preferred: str = "gemini",
    temperature: float = 0.7,
    max_tokens: int = 8192,
    log=None,
) -> dict:
    """
    Universal AI call with automatic fallback.

    Returns:
        {
            "success":  True/False,
            "provider": "Gemini" | "Groq",
            "model":    "model-name",
            "text":     "response text",
            "error":    "error message if failed",
            "elapsed":  seconds
        }
    """
    keys = _load_keys()

    # Order providers by preference
    ordered = sorted(
        PROVIDERS,
        key=lambda p: 0 if p["name"].lower() == preferred.lower() else 1
    )

    last_error = ""

    for provider in ordered:
        if not keys.get(provider["key"], ""):
            _log(log, f"[AI Router] ⏭ Skipping {provider['name']} — no API key")
            continue

        for model in provider["models"]:
            try:
                _log(log, f"[AI Router] 🤖 Trying {provider['name']} ({model})...")
                start = time.time()

                text = provider["fn"](
                    prompt=prompt,
                    system=system,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                elapsed = round(time.time() - start, 2)
                _log(log, f"[AI Router] ✅ {provider['name']} ({model}) in {elapsed}s")

                return {
                    "success":  True,
                    "provider": provider["name"],
                    "model":    model,
                    "text":     text,
                    "error":    "",
                    "elapsed":  elapsed,
                }

            except Exception as e:
                last_error = str(e)
                _log(
                    log,
                    f"[AI Router] ❌ {provider['name']} ({model}) failed: "
                    f"{last_error[:120]}"
                )
                if "429" in last_error or "quota" in last_error.lower():
                    _log(log, "[AI Router] ⏳ Rate limited — waiting 3s...")
                    time.sleep(3)
                elif "404" in last_error or "NOT_FOUND" in last_error:
                    # Model not found — skip to next model immediately
                    _log(log, f"[AI Router] Model {model} not found — trying next...")
                continue

    return {
        "success":  False,
        "provider": "None",
        "model":    "None",
        "text":     "",
        "error":    last_error,
    }


# ── Shortcuts ─────────────────────────────────────────────────────────────────

def ask_gemini(prompt: str, system: str = "", **kwargs) -> str:
    result = ask_ai(prompt, system=system, preferred="gemini", **kwargs)
    return result["text"] if result["success"] else f"AI Error: {result['error']}"


def ask_grok(prompt: str, system: str = "", **kwargs) -> str:
    result = ask_ai(prompt, system=system, preferred="grok", **kwargs)
    return result["text"] if result["success"] else f"AI Error: {result['error']}"


def ask_best(prompt: str, system: str = "", **kwargs) -> str:
    result = ask_ai(prompt, system=system, preferred="gemini", **kwargs)
    return result["text"] if result["success"] else f"AI Error: {result['error']}"


def _log(player, message: str):
    print(message)
    if player:
        try:
            player.write_log(message[:200])
        except Exception:
            pass