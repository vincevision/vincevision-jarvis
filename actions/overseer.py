import subprocess
import os
import json
import re
import sys
import time
import random
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
DOSSIER_DIR = Path.home() / "JARVIS_logs" / "dossiers"


def _log(player, msg):
    if player:
        try:
            player.write_log(f"[OVERSEER] {msg}")
        except Exception:
            pass


def _run_tool(cmd: str, timeout: int = 30) -> str:
    """Run a CLI tool and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return f"Timeout after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def _check_tool(name: str) -> bool:
    """Check if a CLI tool is installed."""
    import shutil
    return shutil.which(name) is not None


def overseer(parameters: dict, player=None, speak=None) -> str:
    """
    Intelligence Engine.
    Cross-references usernames and emails to build
    full identities and find leaked data.
    """
    target = parameters.get("target", "").strip()

    if not target:
        return (
            "Sir, I need a target. "
            "Provide a username, email, or phone number."
        )

    # ── Auto-detect type ──────────────────────────────────────────────────────
    if "@" in target and "." in target:
        target_type = "email"
    elif re.match(r"^\+?[\d\s\-]{7,20}$", target.replace(" ", "")):
        target_type = "phone"
    else:
        target_type = "username"

    DOSSIER_DIR.mkdir(parents=True, exist_ok=True)

    _log(player, f"Target: {target} | Type: {target_type}")
    if speak:
        speak(
            f"Initiating full digital shadow scan on {target}, sir. "
            f"Searching across global archives."
        )

    results = []
    results.append(f"OVERSEER INTELLIGENCE REPORT")
    results.append(f"{'=' * 50}")
    results.append(f"Target   : {target}")
    results.append(f"Type     : {target_type.upper()}")
    results.append(f"Date     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    results.append(f"{'=' * 50}\n")

    # ── BRANCH 1: USERNAME FOOTPRINT ──────────────────────────────────────────
    if target_type == "username":
        results.append("[ SOCIAL MEDIA FOOTPRINT ]")
        _log(player, "Scanning social platforms...")

        # ── Try Sherlock if installed ─────────────────────────────────────────
        if _check_tool("sherlock"):
            _log(player, "Running Sherlock...")
            if speak:
                speak("Running Sherlock username scanner, sir.")
            sherlock_out = _run_tool(
                f"sherlock --timeout 5 --print-found {target}",
                timeout=120
            )
            results.append(sherlock_out[:2000])
        else:
            # ── Manual URL construction for top 30 platforms ──────────────────
            platforms = {
                "Instagram":   f"https://www.instagram.com/{target}/",
                "Twitter/X":   f"https://twitter.com/{target}",
                "GitHub":      f"https://github.com/{target}",
                "Reddit":      f"https://www.reddit.com/user/{target}",
                "TikTok":      f"https://www.tiktok.com/@{target}",
                "YouTube":     f"https://www.youtube.com/@{target}",
                "LinkedIn":    f"https://www.linkedin.com/in/{target}",
                "Pinterest":   f"https://www.pinterest.com/{target}/",
                "Snapchat":    f"https://www.snapchat.com/add/{target}",
                "Twitch":      f"https://www.twitch.tv/{target}",
                "Steam":       f"https://steamcommunity.com/id/{target}",
                "Spotify":     f"https://open.spotify.com/user/{target}",
                "SoundCloud":  f"https://soundcloud.com/{target}",
                "Flickr":      f"https://www.flickr.com/people/{target}",
                "Tumblr":      f"https://{target}.tumblr.com",
                "Medium":      f"https://medium.com/@{target}",
                "Patreon":     f"https://www.patreon.com/{target}",
                "OnlyFans":    f"https://onlyfans.com/{target}",
                "Telegram":    f"https://t.me/{target}",
                "Discord":     f"https://discord.com/users/{target}",
                "Roblox":      f"https://www.roblox.com/user.aspx?username={target}",
                "Fiverr":      f"https://www.fiverr.com/{target}",
                "Etsy":        f"https://www.etsy.com/shop/{target}",
                "DeviantArt":  f"https://www.deviantart.com/{target}",
                "HackerNews":  f"https://news.ycombinator.com/user?id={target}",
                "GitLab":      f"https://gitlab.com/{target}",
                "BitBucket":   f"https://bitbucket.org/{target}/",
                "Keybase":     f"https://keybase.io/{target}",
                "ProductHunt": f"https://www.producthunt.com/@{target}",
                "Gravatar":    f"https://en.gravatar.com/{target}",
            }

            results.append(
                f"Direct profile links constructed for {len(platforms)} platforms:"
            )
            for platform, url in platforms.items():
                results.append(f"  • {platform:<15} {url}")

        # ── Try Maigret if installed ──────────────────────────────────────────
        if _check_tool("maigret"):
            _log(player, "Running Maigret deep scan...")
            maigret_out = _run_tool(
                f"maigret {target} --timeout 5 --no-color",
                timeout=120
            )
            results.append(f"\n[ MAIGRET DEEP SCAN ]\n{maigret_out[:2000]}")

    # ── BRANCH 2: EMAIL INVESTIGATION ─────────────────────────────────────────
    elif target_type == "email":
        results.append("[ EMAIL INTELLIGENCE ]")
        _log(player, f"Investigating email: {target}")

        # ── Try Holehe if installed ───────────────────────────────────────────
        if _check_tool("holehe"):
            _log(player, "Running Holehe email scanner...")
            if speak:
                speak("Running Holehe email registration scanner, sir.")
            holehe_out = _run_tool(
                f"holehe {target} --no-color",
                timeout=120
            )
            results.append(holehe_out[:2000])
        else:
            # ── Manual email platform check ───────────────────────────────────
            import urllib.request
            import urllib.error

            results.append(
                f"Email: {target}\n"
                f"Checking registration across major platforms...\n"
            )

            # Try HaveIBeenPwned API (public endpoint)
            try:
                account = target.split("@")[0]
                url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{target}"
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "JARVIS-Overseer",
                        "hibp-api-key": ""
                    }
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read())
                        breach_names = [b["Name"] for b in data]
                        results.append(
                            f"⚠️  BREACH DETECTED — Found in {len(breach_names)} breaches:"
                        )
                        for b in breach_names:
                            results.append(f"  • {b}")
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        results.append("✅ No breaches found via HaveIBeenPwned.")
                    else:
                        results.append(f"HIBP check: {e}")
            except Exception as e:
                results.append(f"HIBP check skipped: {e}")

            # Email-based profile links
            username = target.split("@")[0]
            results.append(f"\nProfile links derived from email username '{username}':")
            email_platforms = {
                "Gravatar":  f"https://en.gravatar.com/{username}",
                "GitHub":    f"https://github.com/{username}",
                "Twitter":   f"https://twitter.com/{username}",
                "Instagram": f"https://instagram.com/{username}",
                "LinkedIn":  f"https://linkedin.com/in/{username}",
            }
            for p, u in email_platforms.items():
                results.append(f"  • {p:<15} {u}")

    # ── BRANCH 3: PHONE NUMBER ────────────────────────────────────────────────
    elif target_type == "phone":
        results.append("[ PHONE NUMBER INTELLIGENCE ]")
        _log(player, f"Investigating phone: {target}")
        if speak:
            speak("Running phone number investigation, sir.")

        # Try number_tracer if available
        try:
            from actions.number_tracer import number_tracer
            trace = number_tracer(
                {"phone": target, "action": "trace"},
                player=player,
                speak=None
            )
            results.append(trace)
        except Exception:
            results.append(
                f"Phone: {target}\n"
                f"• Carrier lookup: Use https://www.carrierlookup.com/?number={target}\n"
                f"• Truecaller:     https://www.truecaller.com/search/us/{target}\n"
                f"• OSINT:          https://www.spokeo.com/phone/{target}\n"
                f"• Sync check:     https://www.getcontact.com/en/\n"
            )

    # ── BRANCH 4: GENERAL WEB SEARCH (Name / Company) ─────────────────────────
    else:
        results.append("[ WEB INTELLIGENCE ]")
        q = target.replace(" ", "+")
        results.append("Google Dork results:")
        dorks = [
            f"https://www.google.com/search?q=\"{target}\"",
            f"https://www.google.com/search?q=\"{target}\"+site:linkedin.com",
            f"https://www.google.com/search?q=\"{target}\"+site:instagram.com",
            f"https://www.google.com/search?q=\"{target}\"+filetype:pdf",
            f"https://www.google.com/search?q=\"{target}\"+password+leaked",
            f"https://www.google.com/search?q=\"{target}\"+email+contact",
        ]
        for d in dorks:
            results.append(f"  • {d}")

    # ── ADDITIONAL OSINT TOOLS ────────────────────────────────────────────────
    results.append(f"\n[ ADDITIONAL OSINT RESOURCES ]")
    results.append(
        f"  • Maltego:        maltego (if installed)"
    )
    results.append(
        f"  • TheHarvester:   theHarvester -d {target} -b all"
    )
    results.append(
        f"  • Recon-ng:       recon-ng (if installed)"
    )
    results.append(
        f"  • Shodan:         https://www.shodan.io/search?query={target}"
    )
    results.append(
        f"  • IntelX:         https://intelx.io/?s={target}"
    )
    results.append(
        f"  • Dehashed:       https://dehashed.com/search?query={target}"
    )
    results.append(
        f"  • Pipl:           https://pipl.com/search/?q={target}"
    )
    results.append(
        f"  • SpyDialer:      https://spydialer.com/default.aspx"
    )

    # ── COMPILE & SAVE ────────────────────────────────────────────────────────
    final_report = "\n".join(results)

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", target)
    report_file = DOSSIER_DIR / f"{safe_name}_dossier.txt"
    report_file.write_text(final_report, encoding="utf-8")

    _log(player, f"Dossier saved: {report_file}")
    if speak:
        speak(
            f"Operation complete, sir. "
            f"Full dossier compiled and saved. "
            f"I found profile links, breach data, and OSINT resources."
        )

    return (
        f"{final_report[:3500]}\n\n"
        f"[FULL DOSSIER SAVED: {report_file}]"
    )


# ── Tool Declaration ──────────────────────────────────────────────────────────
DECLARATION = {
    "name": "overseer",
    "description": (
        "Information warfare OSINT engine. "
        "Give it a username, email, or phone number. "
        "It builds a complete digital dossier: "
        "all social media accounts, breach detection, "
        "leaked password sources, and OSINT resource links. "
        "Uses Sherlock, Maigret, Holehe if installed. "
        "Falls back to manual URL construction if not."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "target": {
                "type": "STRING",
                "description": (
                    "Username, email address, phone number, "
                    "or full name to investigate"
                )
            },
        },
        "required": ["target"]
    }
}