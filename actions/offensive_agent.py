# actions/offensive_agent.py

"""
JARVIS Offensive Security Agent
Dispatcher for: WiFi, Payload, OSINT, Dark Web, Keylogger, Exploit agents.
"""

from actions.off_wifi      import run_wifi_agent
from actions.off_payload   import run_payload_agent
from actions.off_osint     import run_osint_agent
from actions.off_darkweb   import run_darkweb_agent
from actions.off_keylogger import run_keylogger_agent
from actions.off_exploit   import run_exploit_agent
from actions.off_phishing import run_phishing_agent


_SUB_AGENTS = {
    "wifi":       run_wifi_agent,
    "payload":    run_payload_agent,
    "osint":      run_osint_agent,
    "darkweb":    run_darkweb_agent,
    "dark_web":   run_darkweb_agent,
    "keylogger":  run_keylogger_agent,
    "exploit":    run_exploit_agent,
    "phishing": run_phishing_agent,
}


def offensive_agent(
    parameters: dict,
    player=None,
    speak=None
) -> str:
    """
    Main entry point for the offensive security agent.
    Expects parameters dict with at least 'agent' and 'action' keys.
    """
    agent_name = parameters.get("agent", "").lower().strip()
    handler    = _SUB_AGENTS.get(agent_name)

    if not handler:
        available = ", ".join(_SUB_AGENTS.keys())
        return (
            f"Unknown agent: '{agent_name}'. "
            f"Available agents: {available}"
        )

    try:
        return handler(parameters, speak=speak, player=player) or "Done."
    except Exception as e:
        import traceback
        traceback.print_exc()
        err = f"Offensive agent '{agent_name}' error: {e}"
        if player:
            player.write_log(f"[Offensive] ERROR: {err}")
        if speak:
            speak(f"Sir, the {agent_name} agent encountered an error: {str(e)[:100]}")
        return err