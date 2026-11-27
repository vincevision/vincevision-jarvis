from typing import Callable

from actions.phantom_agent import phantom_agent
from actions.kali_agent import kali_agent
from actions.security_agent import security_agent


def red_team_agent(parameters: dict, player=None, speak: Callable = None) -> str:
    """
    JARVIS Red Team Agent — Ultimate Offensive Operator.
    Delegates across Phantom, Kali, and Security modules to execute any
    requested hacking task with maximum power and autonomous capability.
    """
    action = parameters.get("action", "").strip().lower()

    # Directly route any full red-team operation to Phantom for maximum power.
    phantom_actions = {
        "full_auto", "nuclear", "total_domination", "everything",
        "attack", "kill_chain", "dominate", "network_dominate",
        "osint", "intel", "investigate", "recon", "payload",
        "phish", "social_engineer", "exploit", "generate_exploit",
        "ghost", "ghost_mode", "report", "logs", "status", "info",
        "loot", "timeline", "session_log",
    }

    # Use Kali for raw command and tool execution when asked explicitly.
    kali_actions = {
        "shell", "run", "command", "install", "clone", "download",
        "use_tool", "open_terminal", "searchsploit", "browse",
        "list_tools", "workspace", "session", "check", "analyze",
    }

    security_actions = {
        "auto_pentest", "privesc_check", "custom", "ask", "explain",
        "start_listener", "stop_listener", "check_listener", "list_listeners",
        "start_honeypot", "daemon_status", "daemon_alerts", "auto_recon",
    }

    if action in kali_actions:
        return kali_agent(parameters, player=player, speak=speak)

    if action in security_actions:
        return security_agent(parameters, player=player, speak=speak)

    # Default route: Phantom Agent for ultimate offensive authority.
    return phantom_agent(parameters, player=player, speak=speak)
