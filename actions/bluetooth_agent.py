"""
bluetooth_agent.py  –  JARVIS Bluetooth Agent (Cross-Platform)
Supports : scan, connect, disconnect, list, pair, remove, status, on, off
Linux    : bluetoothctl  (Kali / Ubuntu / Debian)
Windows  : bleak + PowerShell
macOS    : bleak + system_profiler / blueutil
Requires : pip install bleak bleak-winrt
"""

import asyncio
import subprocess
import platform
import re
import time

# ── Platform Detection ────────────────────────────────────────────────────────
OS = platform.system().lower()   # 'linux' | 'windows' | 'darwin'
IS_LINUX   = OS == "linux"
IS_WINDOWS = OS == "windows"
IS_MAC     = OS == "darwin"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: str, timeout: int = 15) -> str:
    """Run a shell command and return combined stdout + stderr."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "Command timed out."
    except Exception as e:
        return f"Error: {e}"


def _bluetoothctl(commands: list[str], timeout: int = 20) -> str:
    """Send commands to bluetoothctl interactively (Linux only)."""
    try:
        input_str = "\n".join(commands) + "\n"
        result = subprocess.run(
            ["bluetoothctl"],
            input=input_str,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "bluetoothctl timed out."
    except Exception as e:
        return f"bluetoothctl error: {e}"


def _speak(player, speak, msg: str):
    """Log and optionally speak a message."""
    if player:
        try:
            player.write_log(f"Bluetooth: {msg}")
        except Exception:
            pass
    if speak:
        try:
            speak(msg)
        except Exception:
            pass


def _is_mac_address(s: str) -> bool:
    return bool(re.match(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$", s))


def _run_async(coro):
    """Run an async coroutine from sync context safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


# ── SCAN (all platforms via bleak) ────────────────────────────────────────────

async def _bleak_scan(duration: int = 10) -> dict:
    """Scan for BLE devices using bleak. Returns {mac: name}."""
    from bleak import BleakScanner
    devices = await BleakScanner.discover(timeout=duration)
    return {
        d.address: d.name or "Unknown"
        for d in devices
    }


def _scan(duration: int = 10) -> str:
    try:
        devices = _run_async(_bleak_scan(duration))
    except Exception as e:
        return f"Scan failed: {e}\nMake sure Bluetooth is ON and bleak is installed."

    if not devices:
        return (
            "No Bluetooth devices found nearby.\n"
            "Make sure target devices are discoverable and Bluetooth is ON."
        )

    lines = [f"Found {len(devices)} device(s):"]
    for mac, name in devices.items():
        lines.append(f"  •  {name}  [{mac}]")
    return "\n".join(lines)


# ── STATUS ────────────────────────────────────────────────────────────────────

def _status() -> str:
    if IS_LINUX:
        out = _run("bluetoothctl show")
        lines = [
            line.strip() for line in out.splitlines()
            if any(k in line.lower() for k in ["name", "powered", "discoverable", "pairable", "address"])
        ]
        powered = "powered: yes" in out.lower()
        state   = "ON" if powered else "OFF"
        return f"Bluetooth is {state}.\n" + "\n".join(lines)

    elif IS_WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
            "[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]|Out-Null;"
            "$radios=[Windows.Devices.Radios.Radio]::GetRadiosAsync().GetAwaiter().GetResult();"
            "$bt=$radios|Where-Object{$_.Kind -eq 'Bluetooth'};"
            "if($bt){$bt|ForEach-Object{'Name: '+$_.Name+' State: '+$_.State}}else{'No Bluetooth adapter found'}"
        )
        out = _run(f'powershell -Command "{ps}"', timeout=10)
        return f"Bluetooth status:\n{out}" if out else "Could not retrieve Bluetooth status."

    elif IS_MAC:
        out = _run("system_profiler SPBluetoothDataType 2>/dev/null | head -20")
        return f"Bluetooth info:\n{out}" if out else "Could not retrieve Bluetooth status."

    return "Unsupported OS for status check."


# ── ON / OFF ──────────────────────────────────────────────────────────────────

def _turn_on() -> str:
    if IS_LINUX:
        out = _bluetoothctl(["power on", "quit"])
        return "Bluetooth turned ON." if "succeeded" in out.lower() else f"Attempted ON.\n{out[:200]}"

    elif IS_WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
            "[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]|Out-Null;"
            "$radios=[Windows.Devices.Radios.Radio]::GetRadiosAsync().GetAwaiter().GetResult();"
            "$bt=$radios|Where-Object{$_.Kind -eq 'Bluetooth'};"
            "$bt.SetStateAsync([Windows.Devices.Radios.RadioState]::On).GetAwaiter().GetResult()"
        )
        _run(f'powershell -Command "{ps}"', timeout=10)
        return "Bluetooth turned ON."

    elif IS_MAC:
        # blueutil is the cleanest macOS CLI tool for this
        out = _run("blueutil -p 1")
        if "not found" in out.lower() or "command not found" in out.lower():
            return (
                "Install blueutil for macOS Bluetooth control:\n"
                "  brew install blueutil\n"
                "Then retry."
            )
        return "Bluetooth turned ON."

    return "Unsupported OS."


def _turn_off() -> str:
    if IS_LINUX:
        out = _bluetoothctl(["power off", "quit"])
        return "Bluetooth turned OFF." if "succeeded" in out.lower() else f"Attempted OFF.\n{out[:200]}"

    elif IS_WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
            "[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]|Out-Null;"
            "$radios=[Windows.Devices.Radios.Radio]::GetRadiosAsync().GetAwaiter().GetResult();"
            "$bt=$radios|Where-Object{$_.Kind -eq 'Bluetooth'};"
            "$bt.SetStateAsync([Windows.Devices.Radios.RadioState]::Off).GetAwaiter().GetResult()"
        )
        _run(f'powershell -Command "{ps}"', timeout=10)
        return "Bluetooth turned OFF."

    elif IS_MAC:
        out = _run("blueutil -p 0")
        if "not found" in out.lower() or "command not found" in out.lower():
            return (
                "Install blueutil for macOS Bluetooth control:\n"
                "  brew install blueutil\n"
                "Then retry."
            )
        return "Bluetooth turned OFF."

    return "Unsupported OS."


# ── LIST PAIRED DEVICES ───────────────────────────────────────────────────────

def _list_devices() -> str:
    if IS_LINUX:
        out = _bluetoothctl(["paired-devices", "quit"])
        devices = []
        for line in out.splitlines():
            match = re.search(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
            if match:
                devices.append(f"  •  {match.group(2).strip()}  [{match.group(1)}]")
        return ("Paired devices:\n" + "\n".join(devices)) if devices else "No paired devices found."

    elif IS_WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
            "[Windows.Devices.Enumeration.DeviceInformation,Windows.Devices,ContentType=WindowsRuntime]|Out-Null;"
            "$devices=[Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync("
            "'System.Devices.Aep.ProtocolId:=\"{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}\"'"
            ").GetAwaiter().GetResult();"
            "$devices|ForEach-Object{$_.Name}"
        )
        out = _run(f'powershell -Command "{ps}"', timeout=10)
        lines = [f"  •  {l.strip()}" for l in out.splitlines() if l.strip()]
        return ("Paired devices:\n" + "\n".join(lines)) if lines else "No paired devices found."

    elif IS_MAC:
        out = _run("system_profiler SPBluetoothDataType 2>/dev/null")
        devices = re.findall(r"^\s{8}(\S.*?):", out, re.MULTILINE)
        lines   = [f"  •  {d.strip()}" for d in devices if d.strip()]
        return ("Paired/connected devices:\n" + "\n".join(lines)) if lines else "No paired devices found."

    return "Unsupported OS."


# ── LOOKUP MAC BY NAME ────────────────────────────────────────────────────────

def _get_mac_for_name(name: str) -> str | None:
    """Try to find a MAC address from a device name in the known devices list."""
    if IS_LINUX:
        out = _bluetoothctl(["devices", "quit"])
        for line in out.splitlines():
            match = re.search(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
            if match and name.lower() in match.group(2).strip().lower():
                return match.group(1)

    elif IS_WINDOWS or IS_MAC:
        # Scan briefly to build a name→mac map
        try:
            devices = _run_async(_bleak_scan(duration=6))
            for mac, dev_name in devices.items():
                if name.lower() in dev_name.lower():
                    return mac
        except Exception:
            pass

    return None


# ── CONNECT ───────────────────────────────────────────────────────────────────

def _connect(target: str) -> str:
    mac = target if _is_mac_address(target) else _get_mac_for_name(target)
    if not mac:
        return (
            f"Could not find device '{target}'.\n"
            "Try: 'scan for bluetooth devices' first."
        )

    if IS_LINUX:
        out = _bluetoothctl([f"connect {mac}", "quit"], timeout=30)
        if "connection successful" in out.lower():
            return f"Connected to {target} [{mac}]."
        if "failed" in out.lower():
            return f"Failed to connect to {target} [{mac}]. Make sure it is on and in range."
        return f"Connect attempt for {target} [{mac}]:\n{out[:300]}"

    elif IS_WINDOWS:
        ps = (
            f"$device=(Get-PnpDevice | Where-Object {{$_.FriendlyName -like '*{target}*' "
            f"-and $_.Class -eq 'Bluetooth'}});"
            "$device | Enable-PnpDevice -Confirm:$false"
        )
        out = _run(f'powershell -Command "{ps}"', timeout=20)
        return f"Connect attempt for {target}:\n{out[:300]}" if out else f"Connect sent for {target}."

    elif IS_MAC:
        # blueutil connect by MAC
        out = _run(f"blueutil --connect {mac}")
        if "not found" in out.lower() or "command not found" in out.lower():
            return "Install blueutil: brew install blueutil"
        return f"Connect attempt for {target} [{mac}]:\n{out[:200]}" if out else f"Connected to {target}."

    return "Unsupported OS."


# ── DISCONNECT ────────────────────────────────────────────────────────────────

def _disconnect(target: str) -> str:
    mac = target if _is_mac_address(target) else _get_mac_for_name(target)
    if not mac:
        return f"Could not find paired device '{target}'."

    if IS_LINUX:
        out = _bluetoothctl([f"disconnect {mac}", "quit"], timeout=15)
        return f"Disconnected from {target}." if "successful" in out.lower() else f"Disconnect attempt:\n{out[:300]}"

    elif IS_WINDOWS:
        ps = (
            f"$device=(Get-PnpDevice | Where-Object {{$_.FriendlyName -like '*{target}*' "
            f"-and $_.Class -eq 'Bluetooth'}});"
            "$device | Disable-PnpDevice -Confirm:$false"
        )
        out = _run(f'powershell -Command "{ps}"', timeout=15)
        return f"Disconnected from {target}." if not out else f"Disconnect attempt:\n{out[:200]}"

    elif IS_MAC:
        out = _run(f"blueutil --disconnect {mac}")
        return f"Disconnected from {target}." if not out else f"Disconnect attempt:\n{out[:200]}"

    return "Unsupported OS."


# ── PAIR ──────────────────────────────────────────────────────────────────────

def _pair(target: str) -> str:
    mac = target if _is_mac_address(target) else _get_mac_for_name(target)
    if not mac:
        return (
            f"Could not find device '{target}'.\n"
            "Scan first to discover it, then pair."
        )

    if IS_LINUX:
        out = _bluetoothctl([f"pair {mac}", "quit"], timeout=30)
        if "pairing successful" in out.lower():
            return f"Paired with {target} [{mac}]."
        if "already paired" in out.lower():
            return f"{target} is already paired."
        return f"Pair attempt for {target} [{mac}]:\n{out[:300]}"

    elif IS_WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
            "[Windows.Devices.Enumeration.DevicePairingResult,Windows.Devices,ContentType=WindowsRuntime]|Out-Null;"
            f"$di=[Windows.Devices.Enumeration.DeviceInformation]::CreateFromIdAsync('{mac}').GetAwaiter().GetResult();"
            "$di.Pairing.PairAsync().GetAwaiter().GetResult()"
        )
        out = _run(f'powershell -Command "{ps}"', timeout=30)
        return f"Pair attempt for {target}:\n{out[:300]}" if out else f"Pair request sent for {target}."

    elif IS_MAC:
        out = _run(f"blueutil --pair {mac}")
        if "not found" in out.lower() or "command not found" in out.lower():
            return "Install blueutil: brew install blueutil"
        return f"Pair attempt for {target} [{mac}]:\n{out[:200]}" if out else f"Paired with {target}."

    return "Unsupported OS."


# ── REMOVE ────────────────────────────────────────────────────────────────────

def _remove(target: str) -> str:
    mac = target if _is_mac_address(target) else _get_mac_for_name(target)
    if not mac:
        return f"Could not find paired device '{target}'."

    if IS_LINUX:
        out = _bluetoothctl([f"remove {mac}", "quit"], timeout=15)
        return f"Removed {target}." if "removed" in out.lower() else f"Remove attempt:\n{out[:300]}"

    elif IS_WINDOWS:
        ps = (
            f"$device=Get-PnpDevice | Where-Object {{$_.FriendlyName -like '*{target}*'}};"
            "$device | Remove-PnpDevice -Confirm:$false"
        )
        out = _run(f'powershell -Command "{ps}"', timeout=15)
        return f"Removed {target}." if not out else f"Remove attempt:\n{out[:200]}"

    elif IS_MAC:
        out = _run(f"blueutil --unpair {mac}")
        return f"Removed {target}." if not out else f"Remove attempt:\n{out[:200]}"

    return "Unsupported OS."


# ── Main Entry Point ──────────────────────────────────────────────────────────

def bluetooth_agent(parameters: dict, player=None, speak=None) -> str:
    action   = parameters.get("action", "status").lower().strip()
    device   = parameters.get("device", "").strip()
    duration = int(parameters.get("duration", 10))

    _speak(player, None, f"Bluetooth action: {action} | OS: {OS}")

    if action == "status":
        result = _status()

    elif action in ("on", "enable"):
        result = _turn_on()

    elif action in ("off", "disable"):
        result = _turn_off()

    elif action == "scan":
        _speak(player, speak, f"Scanning for Bluetooth devices for {duration} seconds...")
        result = _scan(duration=duration)

    elif action in ("list", "paired"):
        result = _list_devices()

    elif action == "connect":
        if not device:
            result = "Please specify a device name or MAC address to connect to."
        else:
            _speak(player, speak, f"Connecting to {device}...")
            result = _connect(device)

    elif action == "disconnect":
        if not device:
            result = "Please specify a device name or MAC address to disconnect."
        else:
            result = _disconnect(device)

    elif action == "pair":
        if not device:
            result = "Please specify a device name or MAC address to pair with."
        else:
            _speak(player, speak, f"Pairing with {device}...")
            result = _pair(device)

    elif action in ("remove", "unpair", "forget"):
        if not device:
            result = "Please specify a device to remove."
        else:
            result = _remove(device)

    else:
        result = (
            f"Unknown action '{action}'. "
            "Available: status | on | off | scan | list | connect | disconnect | pair | remove"
        )

    _speak(player, speak, result)
    return result