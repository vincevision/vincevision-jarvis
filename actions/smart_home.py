# smart_home.py
"""
JARVIS Smart Home Agent
────────────────────────
Supports:
  - Home Assistant (local or cloud)
  - Philips Hue (direct)
  - TP-Link Tapo (direct)
  - Tuya/Smart Life (cloud)
  - Generic MQTT devices
  - Xiaomi Mi Home
  - Google Home (via browser)
  - Amazon Alexa (via browser)

Features:
  - Control lights (on/off/brightness/color)
  - Control switches and plugs
  - Read sensors (temperature/humidity/motion)
  - Control climate (thermostat/AC/fan)
  - Lock/unlock doors
  - Control cameras
  - Scene activation
  - Automation triggers
  - Device discovery
  - Energy monitoring
"""

import json
import sys
import time
import platform
import requests
import socket
import threading
from pathlib  import Path
from datetime import datetime

_OS = platform.system()


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
SMARTHOME_CONFIG = BASE_DIR / "config" / "smart_home.json"


def _load_config() -> dict:
    if not SMARTHOME_CONFIG.exists():
        return {}
    try:
        with open(SMARTHOME_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(config: dict):
    SMARTHOME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(SMARTHOME_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ─────────────────────────────────────────────
# HOME ASSISTANT
# ─────────────────────────────────────────────

class HomeAssistant:
    """
    Controls Home Assistant via REST API.
    Works with local and cloud (Nabu Casa) installations.
    """

    def __init__(self, host: str, token: str, port: int = 8123, ssl: bool = False):
        protocol  = "https" if ssl else "http"
        self.base = f"{protocol}://{host}:{port}/api"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

    def _get(self, endpoint: str) -> dict | list:
        r = requests.get(
            f"{self.base}{endpoint}",
            headers=self.headers,
            timeout=10
        )
        r.raise_for_status()
        return r.json()

    def _post(self, endpoint: str, data: dict = None) -> dict:
        r = requests.post(
            f"{self.base}{endpoint}",
            headers=self.headers,
            json=data or {},
            timeout=10
        )
        r.raise_for_status()
        return r.json()

    def get_states(self) -> list:
        """Get all entity states."""
        return self._get("/states")

    def get_state(self, entity_id: str) -> dict:
        """Get state of a specific entity."""
        return self._get(f"/states/{entity_id}")

    def call_service(self, domain: str, service: str, data: dict) -> dict:
        """Call a Home Assistant service."""
        return self._post(f"/services/{domain}/{service}", data)

    def turn_on(self, entity_id: str, **kwargs) -> str:
        data = {"entity_id": entity_id, **kwargs}
        self.call_service(entity_id.split(".")[0], "turn_on", data)
        return f"Turned on: {entity_id}"

    def turn_off(self, entity_id: str) -> str:
        self.call_service(
            entity_id.split(".")[0], "turn_off",
            {"entity_id": entity_id}
        )
        return f"Turned off: {entity_id}"

    def toggle(self, entity_id: str) -> str:
        self.call_service(
            entity_id.split(".")[0], "toggle",
            {"entity_id": entity_id}
        )
        return f"Toggled: {entity_id}"

    def set_brightness(self, entity_id: str, brightness: int) -> str:
        """Set brightness 0-100."""
        brightness_255 = int(brightness * 2.55)
        self.call_service("light", "turn_on", {
            "entity_id": entity_id,
            "brightness": brightness_255
        })
        return f"Brightness set to {brightness}%: {entity_id}"

    def set_color(self, entity_id: str, color: str) -> str:
        """Set light color by name or RGB."""
        color_map = {
            "red":    [255, 0,   0  ],
            "green":  [0,   255, 0  ],
            "blue":   [0,   0,   255],
            "white":  [255, 255, 255],
            "yellow": [255, 255, 0  ],
            "purple": [128, 0,   128],
            "orange": [255, 165, 0  ],
            "pink":   [255, 192, 203],
            "cyan":   [0,   255, 255],
            "warm":   [255, 200, 100],
            "cool":   [200, 220, 255],
        }
        rgb = color_map.get(color.lower(), [255, 255, 255])
        self.call_service("light", "turn_on", {
            "entity_id": entity_id,
            "rgb_color": rgb
        })
        return f"Color set to {color}: {entity_id}"

    def set_temperature(self, entity_id: str, temperature: float) -> str:
        """Set thermostat temperature."""
        self.call_service("climate", "set_temperature", {
            "entity_id":   entity_id,
            "temperature": temperature
        })
        return f"Temperature set to {temperature}°: {entity_id}"

    def activate_scene(self, scene_id: str) -> str:
        """Activate a scene."""
        self.call_service("scene", "turn_on", {"entity_id": scene_id})
        return f"Scene activated: {scene_id}"

    def lock(self, entity_id: str) -> str:
        self.call_service("lock", "lock", {"entity_id": entity_id})
        return f"Locked: {entity_id}"

    def unlock(self, entity_id: str) -> str:
        self.call_service("lock", "unlock", {"entity_id": entity_id})
        return f"Unlocked: {entity_id}"

    def get_sensor(self, entity_id: str) -> str:
        """Read a sensor value."""
        state = self.get_state(entity_id)
        value = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        unit  = attrs.get("unit_of_measurement", "")
        name  = attrs.get("friendly_name", entity_id)
        return f"{name}: {value}{unit}"

    def find_entity(self, keyword: str) -> list[dict]:
        """Find entities by keyword."""
        states  = self.get_states()
        keyword = keyword.lower()
        matches = []
        for state in states:
            entity_id = state.get("entity_id", "")
            name      = state.get("attributes", {}).get("friendly_name", "")
            if keyword in entity_id.lower() or keyword in name.lower():
                matches.append({
                    "entity_id": entity_id,
                    "name":      name,
                    "state":     state.get("state"),
                })
        return matches

    def get_all_lights(self) -> list[dict]:
        """Get all light entities."""
        states = self.get_states()
        return [
            {
                "entity_id": s["entity_id"],
                "name":      s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                "state":     s["state"],
            }
            for s in states
            if s["entity_id"].startswith("light.")
        ]

    def get_all_switches(self) -> list[dict]:
        """Get all switch entities."""
        states = self.get_states()
        return [
            {
                "entity_id": s["entity_id"],
                "name":      s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                "state":     s["state"],
            }
            for s in states
            if s["entity_id"].startswith("switch.")
        ]


# ─────────────────────────────────────────────
# PHILIPS HUE (DIRECT)
# ─────────────────────────────────────────────

class PhilipsHue:
    """
    Controls Philips Hue lights directly via local bridge.
    No cloud required.
    """

    def __init__(self, bridge_ip: str, username: str):
        self.base = f"http://{bridge_ip}/api/{username}"

    def _get(self, path: str) -> dict:
        r = requests.get(f"{self.base}{path}", timeout=5)
        return r.json()

    def _put(self, path: str, data: dict) -> dict:
        r = requests.put(f"{self.base}{path}", json=data, timeout=5)
        return r.json()

    def get_all_lights(self) -> dict:
        return self._get("/lights")

    def turn_on(self, light_id: str) -> str:
        self._put(f"/lights/{light_id}/state", {"on": True})
        return f"Hue light {light_id} turned on."

    def turn_off(self, light_id: str) -> str:
        self._put(f"/lights/{light_id}/state", {"on": False})
        return f"Hue light {light_id} turned off."

    def set_brightness(self, light_id: str, brightness: int) -> str:
        bri = int(brightness * 2.54)
        self._put(f"/lights/{light_id}/state", {"on": True, "bri": bri})
        return f"Hue light {light_id} brightness set to {brightness}%."

    def set_color_temp(self, light_id: str, temp: str) -> str:
        temps = {"warm": 500, "neutral": 370, "cool": 200, "daylight": 153}
        ct    = temps.get(temp.lower(), 370)
        self._put(f"/lights/{light_id}/state", {"on": True, "ct": ct})
        return f"Hue light {light_id} color temperature set to {temp}."

    def set_color(self, light_id: str, color: str) -> str:
        color_hue = {
            "red":    0,    "orange": 5000,
            "yellow": 10000,"green":  25500,
            "blue":   46920,"purple": 56100,
            "pink":   56100,"white":  0,
        }
        h = color_hue.get(color.lower(), 0)
        self._put(f"/lights/{light_id}/state", {
            "on": True, "hue": h, "sat": 254
        })
        return f"Hue light {light_id} color set to {color}."

    def list_lights(self) -> str:
        lights = self.get_all_lights()
        if not lights:
            return "No Hue lights found."
        lines = ["Philips Hue Lights:"]
        for lid, info in lights.items():
            state  = "ON" if info["state"]["on"] else "OFF"
            name   = info.get("name", f"Light {lid}")
            lines.append(f"  [{lid}] {name} — {state}")
        return "\n".join(lines)

    @staticmethod
    def discover_bridge() -> str | None:
        """Auto-discover Hue bridge on local network."""
        try:
            r = requests.get(
                "https://discovery.meethue.com",
                timeout=5
            )
            bridges = r.json()
            if bridges:
                return bridges[0].get("internalipaddress")
        except Exception:
            pass
        return None

    @staticmethod
    def create_user(bridge_ip: str) -> str:
        """
        Create a new Hue API user.
        Press the link button on the bridge first!
        """
        try:
            r = requests.post(
                f"http://{bridge_ip}/api",
                json={"devicetype": "jarvis#jarvis"},
                timeout=10
            )
            data = r.json()
            if isinstance(data, list) and data:
                if "success" in data[0]:
                    return data[0]["success"]["username"]
                elif "error" in data[0]:
                    return f"Error: {data[0]['error']['description']}"
        except Exception as e:
            return f"Failed: {e}"
        return "Unknown error"


# ─────────────────────────────────────────────
# TP-LINK TAPO (DIRECT)
# ─────────────────────────────────────────────

class TapoDevice:
    """
    Controls TP-Link Tapo smart plugs and bulbs directly.
    """

    def __init__(self, ip: str, email: str, password: str):
        self.ip       = ip
        self.email    = email
        self.password = password
        self._client  = None

    def _get_client(self):
        if self._client is None:
            try:
                from tapo import ApiClient
                import asyncio
                client = ApiClient(self.email, self.password)
                self._client = client
            except ImportError:
                raise ImportError(
                    "tapo library not installed. Run: pip install tapo"
                )
        return self._client

    def turn_on(self) -> str:
        try:
            import asyncio
            from tapo import ApiClient
            async def _do():
                client = ApiClient(self.email, self.password)
                device = await client.p100(self.ip)
                await device.on()
            asyncio.run(_do())
            return f"Tapo device {self.ip} turned on."
        except Exception as e:
            return f"Tapo error: {e}"

    def turn_off(self) -> str:
        try:
            import asyncio
            from tapo import ApiClient
            async def _do():
                client = ApiClient(self.email, self.password)
                device = await client.p100(self.ip)
                await device.off()
            asyncio.run(_do())
            return f"Tapo device {self.ip} turned off."
        except Exception as e:
            return f"Tapo error: {e}"


# ─────────────────────────────────────────────
# MQTT (Generic Smart Home)
# ─────────────────────────────────────────────

class MQTTController:
    """
    Generic MQTT controller for any smart home device.
    Works with Zigbee2MQTT, Tasmota, ESPHome, etc.
    """

    def __init__(self, host: str, port: int = 1883,
                 username: str = None, password: str = None):
        self.host     = host
        self.port     = port
        self.username = username
        self.password = password

    def publish(self, topic: str, payload: str) -> str:
        try:
            import paho.mqtt.publish as publish
            auth = None
            if self.username:
                auth = {"username": self.username, "password": self.password}
            publish.single(
                topic,
                payload=payload,
                hostname=self.host,
                port=self.port,
                auth=auth,
            )
            return f"MQTT published: {topic} → {payload}"
        except ImportError:
            return "paho-mqtt not installed. Run: pip install paho-mqtt"
        except Exception as e:
            return f"MQTT error: {e}"

    def turn_on(self, device: str) -> str:
        return self.publish(f"{device}/set", '{"state": "ON"}')

    def turn_off(self, device: str) -> str:
        return self.publish(f"{device}/set", '{"state": "OFF"}')

    def set_brightness(self, device: str, brightness: int) -> str:
        return self.publish(
            f"{device}/set",
            json.dumps({"state": "ON", "brightness": int(brightness * 2.54)})
        )


# ─────────────────────────────────────────────
# DEVICE DISCOVERY
# ─────────────────────────────────────────────

def _scan_network_for_devices(timeout: int = 3) -> list[dict]:
    """
    Scan local network for common smart home devices.
    Looks for: Hue bridge, Home Assistant, Tapo, etc.
    """
    import subprocess

    # Get local network range
    try:
        result = subprocess.run(
            ["ip", "route"],
            capture_output=True, text=True
        )
        # Find the local network
        network = "192.168.1"
        for line in result.stdout.split("\n"):
            if "src" in line and "192.168" in line:
                parts = line.split()
                for part in parts:
                    if "192.168" in part:
                        network = ".".join(part.split(".")[:3])
                        break
    except Exception:
        network = "192.168.1"

    found   = []
    threads = []
    lock    = threading.Lock()

    def check_host(ip: str):
        """Check if host is up and identify device type."""
        ports_to_check = {
            80:   "HTTP Device",
            8123: "Home Assistant",
            443:  "HTTPS Device",
            1883: "MQTT Broker",
            5000: "Smart Device",
        }
        for port, device_type in ports_to_check.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    # Try to identify the device
                    device_info = {
                        "ip":   ip,
                        "port": port,
                        "type": device_type,
                    }
                    # Try to get more info via HTTP
                    if port in (80, 8123):
                        try:
                            r = requests.get(
                                f"http://{ip}:{port}",
                                timeout=2
                            )
                            if "home-assistant" in r.text.lower():
                                device_info["type"] = "Home Assistant"
                            elif "hue" in r.text.lower():
                                device_info["type"] = "Philips Hue Bridge"
                            elif "tapo" in r.text.lower():
                                device_info["type"] = "TP-Link Tapo"
                        except Exception:
                            pass
                    with lock:
                        found.append(device_info)
                    break
            except Exception:
                pass

    # Scan common IPs
    for i in range(1, 255):
        ip = f"{network}.{i}"
        t  = threading.Thread(target=check_host, args=(ip,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=timeout + 1)

    return found


# ─────────────────────────────────────────────
# CONNECTION FACTORY
# ─────────────────────────────────────────────

def _get_ha_client() -> HomeAssistant | None:
    """Get Home Assistant client from config."""
    config = _load_config()
    ha     = config.get("home_assistant", {})
    if not ha.get("token") or not ha.get("host"):
        return None
    return HomeAssistant(
        host  = ha["host"],
        token = ha["token"],
        port  = ha.get("port", 8123),
        ssl   = ha.get("ssl", False),
    )


def _get_hue_client() -> PhilipsHue | None:
    """Get Philips Hue client from config."""
    config = _load_config()
    hue    = config.get("philips_hue", {})
    if not hue.get("bridge_ip") or not hue.get("username"):
        return None
    return PhilipsHue(
        bridge_ip = hue["bridge_ip"],
        username  = hue["username"],
    )


def _get_mqtt_client() -> MQTTController | None:
    """Get MQTT client from config."""
    config = _load_config()
    mqtt   = config.get("mqtt", {})
    if not mqtt.get("host"):
        return None
    return MQTTController(
        host     = mqtt["host"],
        port     = mqtt.get("port", 1883),
        username = mqtt.get("username"),
        password = mqtt.get("password"),
    )


# ─────────────────────────────────────────────
# SMART ACTIONS
# ─────────────────────────────────────────────

def _resolve_device(
    name: str,
    ha: HomeAssistant = None
) -> str | None:
    """
    Resolve a human-friendly device name to entity_id.
    e.g. "living room light" → "light.living_room"
    """
    if not ha:
        return name

    # Search for matching entity
    matches = ha.find_entity(name)
    if matches:
        return matches[0]["entity_id"]

    # Try common patterns
    clean = name.lower().replace(" ", "_")
    guesses = [
        f"light.{clean}",
        f"switch.{clean}",
        f"climate.{clean}",
        f"lock.{clean}",
        f"cover.{clean}",
        f"fan.{clean}",
        f"media_player.{clean}",
    ]
    for guess in guesses:
        try:
            state = ha.get_state(guess)
            if state:
                return guess
        except Exception:
            pass

    return name


def _control_light(
    action: str,
    device: str,
    brightness: int = None,
    color: str      = None,
    temperature: str = None,
    ha: HomeAssistant = None,
    hue: PhilipsHue   = None,
) -> str:
    """Universal light control."""

    # Try Home Assistant first
    if ha:
        entity_id = _resolve_device(device, ha)
        try:
            if action == "on":
                kwargs = {}
                if brightness is not None:
                    kwargs["brightness"] = int(brightness * 2.55)
                if color:
                    color_map = {
                        "red":    [255, 0,   0  ],
                        "green":  [0,   255, 0  ],
                        "blue":   [0,   0,   255],
                        "white":  [255, 255, 255],
                        "yellow": [255, 255, 0  ],
                        "purple": [128, 0,   128],
                        "orange": [255, 165, 0  ],
                        "pink":   [255, 192, 203],
                        "cyan":   [0,   255, 255],
                        "warm":   [255, 200, 100],
                        "cool":   [200, 220, 255],
                    }
                    rgb = color_map.get(color.lower(), [255, 255, 255])
                    kwargs["rgb_color"] = rgb
                return ha.turn_on(entity_id, **kwargs)
            elif action == "off":
                return ha.turn_off(entity_id)
            elif action == "toggle":
                return ha.toggle(entity_id)
            elif action == "brightness" and brightness is not None:
                return ha.set_brightness(entity_id, brightness)
            elif action == "color" and color:
                return ha.set_color(entity_id, color)
        except Exception as e:
            return f"Home Assistant light error: {e}"

    # Try Philips Hue
    if hue:
        light_id = device.replace("light.", "")
        if action == "on":
            result = hue.turn_on(light_id)
            if brightness:
                result += " " + hue.set_brightness(light_id, brightness)
            if color:
                result += " " + hue.set_color(light_id, color)
            return result
        elif action == "off":
            return hue.turn_off(light_id)
        elif action == "brightness" and brightness:
            return hue.set_brightness(light_id, brightness)
        elif action == "color" and color:
            return hue.set_color(light_id, color)

    return f"No smart home system configured. Say 'Jarvis smart home setup'."


# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

def _run_setup(speak=None) -> str:
    """Interactive smart home setup."""
    print("\n")
    print("═" * 60)
    print("🏠  SMART HOME SETUP")
    print("═" * 60)
    print()
    print("Which smart home system do you use?")
    print()
    print("  1. Home Assistant")
    print("  2. Philips Hue")
    print("  3. MQTT Broker")
    print("  4. Scan network for devices")
    print("  5. Skip")
    print()

    choice = input("Enter number (1-5): ").strip()
    config = _load_config()

    if choice == "1":
        print("\n📌 Home Assistant Setup")
        print("   You need a Long-Lived Access Token from HA")
        print("   Go to: HA → Profile → Long-Lived Access Tokens")
        print()
        host  = input("   HA IP or hostname (e.g. 192.168.1.100): ").strip()
        port  = input("   Port (default 8123): ").strip() or "8123"
        token = input("   Access token: ").strip()
        ssl   = input("   Use HTTPS? (y/n): ").strip().lower() == "y"

        config["home_assistant"] = {
            "host":  host,
            "port":  int(port),
            "token": token,
            "ssl":   ssl,
        }
        _save_config(config)

        # Test connection
        try:
            ha = HomeAssistant(host, token, int(port), ssl)
            states = ha.get_states()
            print(f"\n   ✅ Connected! Found {len(states)} entities.")
            return f"Home Assistant connected. Found {len(states)} entities."
        except Exception as e:
            return f"Connection failed: {e}"

    elif choice == "2":
        print("\n📌 Philips Hue Setup")
        print()

        # Auto discover
        print("   Scanning for Hue bridge...")
        bridge_ip = PhilipsHue.discover_bridge()
        if bridge_ip:
            print(f"   ✅ Found bridge at: {bridge_ip}")
        else:
            bridge_ip = input("   Bridge IP address: ").strip()

        print("\n   Press the LINK BUTTON on your Hue bridge NOW")
        input("   Then press Enter...")

        username = PhilipsHue.create_user(bridge_ip)
        if username and len(username) > 10:
            config["philips_hue"] = {
                "bridge_ip": bridge_ip,
                "username":  username,
            }
            _save_config(config)
            print(f"\n   ✅ Hue connected! Username: {username[:20]}...")
            return f"Philips Hue connected at {bridge_ip}."
        else:
            return f"Hue setup failed: {username}"

    elif choice == "3":
        print("\n📌 MQTT Setup")
        print()
        host     = input("   MQTT broker IP: ").strip()
        port     = input("   Port (default 1883): ").strip() or "1883"
        username = input("   Username (optional): ").strip()
        password = input("   Password (optional): ").strip()

        config["mqtt"] = {
            "host":     host,
            "port":     int(port),
            "username": username or None,
            "password": password or None,
        }
        _save_config(config)
        return f"MQTT broker configured at {host}:{port}."

    elif choice == "4":
        print("\n🔍 Scanning network for smart home devices...")
        devices = _scan_network_for_devices()
        if devices:
            print(f"\n   Found {len(devices)} device(s):")
            for d in devices:
                print(f"   📡 {d['ip']}:{d['port']} — {d['type']}")
            return (
                f"Found {len(devices)} devices:\n" +
                "\n".join(f"{d['ip']}:{d['port']} — {d['type']}" for d in devices)
            )
        return "No smart home devices found on network."

    return "Setup skipped."


# ─────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────

def smart_home(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    """
    Main smart home agent.

    Actions:
        on         — Turn device on
        off        — Turn device off
        toggle     — Toggle device
        brightness — Set light brightness
        color      — Set light color
        temperature — Set thermostat temperature
        scene      — Activate a scene
        lock       — Lock a door
        unlock     — Unlock a door
        status     — Get device status
        list       — List all devices
        list_lights — List all lights
        discover   — Scan for devices
        sensor     — Read a sensor
        setup      — Run setup wizard
        all_on     — Turn all lights on
        all_off    — Turn all lights off
        mqtt       — Send MQTT command
    """
    params      = parameters or {}
    action      = params.get("action",      "status").lower().strip()
    device      = params.get("device",      "").strip()
    room        = params.get("room",        "").strip()
    brightness  = params.get("brightness",  None)
    color       = params.get("color",       "").strip()
    temperature = params.get("temperature", None)
    scene       = params.get("scene",       "").strip()
    topic       = params.get("topic",       "").strip()
    payload     = params.get("payload",     "").strip()

    if brightness is not None:
        brightness = int(brightness)

    if temperature is not None:
        temperature = float(temperature)

    # Resolve device name
    target = device or room
    if not target and action not in (
        "setup", "list", "list_lights", "discover", "all_on", "all_off"
    ):
        target = "all"

    if player:
        player.write_log(f"[SmartHome] {action} → {target or 'all'}")

    # ── Setup ────────────────────────────────────
    if action == "setup":
        return _run_setup(speak=speak)

    # ── Get clients ──────────────────────────────
    ha  = _get_ha_client()
    hue = _get_hue_client()
    mqtt = _get_mqtt_client()

    # No config at all
    if not ha and not hue and not mqtt:
        msg = (
            "No smart home system configured, sir. "
            "Say 'Jarvis smart home setup' to get started."
        )
        if speak:
            speak(msg)
        return msg

    try:

        # ── Turn On ──────────────────────────────
        if action in ("on", "turn_on"):
            if not target or target == "all":
                if ha:
                    lights = ha.get_all_lights()
                    for light in lights:
                        ha.turn_on(light["entity_id"])
                    result = f"Turned on {len(lights)} lights."
                elif hue:
                    lights = hue.get_all_lights()
                    for lid in lights:
                        hue.turn_on(lid)
                    result = f"Turned on {len(lights)} Hue lights."
                else:
                    result = "Please specify a device."
            else:
                result = _control_light(
                    "on", target, brightness, color or None,
                    ha=ha, hue=hue
                )

        # ── Turn Off ─────────────────────────────
        elif action in ("off", "turn_off"):
            if not target or target == "all":
                if ha:
                    lights = ha.get_all_lights()
                    for light in lights:
                        ha.turn_off(light["entity_id"])
                    result = f"Turned off {len(lights)} lights."
                elif hue:
                    lights = hue.get_all_lights()
                    for lid in lights:
                        hue.turn_off(lid)
                    result = f"Turned off {len(lights)} Hue lights."
                else:
                    result = "Please specify a device."
            else:
                result = _control_light("off", target, ha=ha, hue=hue)

        # ── Toggle ───────────────────────────────
        elif action == "toggle":
            if ha:
                entity_id = _resolve_device(target, ha)
                result    = ha.toggle(entity_id)
            elif hue:
                result = "Toggle not supported for Hue directly."
            else:
                result = "No system configured."

        # ── Brightness ───────────────────────────
        elif action == "brightness":
            if brightness is None:
                return "Please specify a brightness level (0-100)."
            result = _control_light(
                "brightness", target, brightness, ha=ha, hue=hue
            )

        # ── Color ────────────────────────────────
        elif action == "color":
            if not color:
                return "Please specify a color."
            result = _control_light(
                "color", target, color=color, ha=ha, hue=hue
            )

        # ── All On ───────────────────────────────
        elif action == "all_on":
            if ha:
                ha.call_service("light", "turn_on", {"entity_id": "all"})
                result = "All lights turned on."
            elif hue:
                lights = hue.get_all_lights()
                for lid in lights:
                    hue.turn_on(lid)
                result = f"All {len(lights)} Hue lights turned on."
            else:
                result = "No system configured."

        # ── All Off ──────────────────────────────
        elif action == "all_off":
            if ha:
                ha.call_service("light", "turn_off", {"entity_id": "all"})
                result = "All lights turned off."
            elif hue:
                lights = hue.get_all_lights()
                for lid in lights:
                    hue.turn_off(lid)
                result = f"All {len(lights)} Hue lights turned off."
            else:
                result = "No system configured."

        # ── Temperature ──────────────────────────
        elif action in ("temperature", "thermostat", "set_temp"):
            if temperature is None:
                return "Please specify a temperature."
            if ha:
                entity_id = _resolve_device(target or "thermostat", ha)
                result    = ha.set_temperature(entity_id, temperature)
            else:
                result = "Temperature control requires Home Assistant."

        # ── Scene ────────────────────────────────
        elif action == "scene":
            scene_name = scene or target
            if not scene_name:
                return "Please specify a scene name."
            if ha:
                entity_id = f"scene.{scene_name.lower().replace(' ', '_')}"
                result    = ha.activate_scene(entity_id)
            else:
                result = "Scene control requires Home Assistant."

        # ── Lock / Unlock ────────────────────────
        elif action == "lock":
            if ha:
                entity_id = _resolve_device(target or "front_door", ha)
                result    = ha.lock(entity_id)
            else:
                result = "Lock control requires Home Assistant."

        elif action == "unlock":
            if ha:
                entity_id = _resolve_device(target or "front_door", ha)
                result    = ha.unlock(entity_id)
            else:
                result = "Lock control requires Home Assistant."

        # ── Status ───────────────────────────────
        elif action in ("status", "state", "check"):
            if not target or target == "all":
                result = _get_summary(ha, hue)
            else:
                if ha:
                    entity_id = _resolve_device(target, ha)
                    try:
                        sensor_result = ha.get_sensor(entity_id)
                        result        = sensor_result
                    except Exception:
                        result = f"Device '{target}' not found."
                else:
                    result = "Status check requires Home Assistant."

        # ── List All ─────────────────────────────
        elif action == "list":
            result = _get_summary(ha, hue)

        # ── List Lights ──────────────────────────
        elif action == "list_lights":
            if ha:
                lights = ha.get_all_lights()
                if not lights:
                    result = "No lights found."
                else:
                    lines = ["Lights:"]
                    for l in lights:
                        icon = "💡" if l["state"] == "on" else "⚫"
                        lines.append(f"  {icon} {l['name']} [{l['entity_id']}]")
                    result = "\n".join(lines)
            elif hue:
                result = hue.list_lights()
            else:
                result = "No system configured."

        # ── Sensor ───────────────────────────────
        elif action == "sensor":
            if ha:
                entity_id = _resolve_device(target, ha)
                result    = ha.get_sensor(entity_id)
            else:
                result = "Sensor reading requires Home Assistant."

        # ── Discover ─────────────────────────────
        elif action == "discover":
            from core.network_scanner import show_scan_gui
            import threading
            threading.Thread(
                target=show_scan_gui,
                kwargs={"speak": speak, "player": player},
                daemon=True
            ).start()
            result = "Network scan started, sir. Opening results window."

        # ── MQTT ─────────────────────────────────
        elif action == "mqtt":
            if not mqtt:
                return "MQTT not configured. Run smart home setup."
            if not topic:
                return "Please specify an MQTT topic."
            result = mqtt.publish(topic, payload or '{"state": "ON"}')

        # ── Unknown ──────────────────────────────
        else:
            result = (
                f"Unknown action: '{action}'. "
                "Try: on, off, toggle, brightness, color, "
                "temperature, scene, lock, unlock, status, list, discover"
            )

        if speak and result and len(result) < 200:
            speak(result)

        return result

    except Exception as e:
        print(f"[SmartHome] Error: {e}")
        return f"Smart home error: {e}"


def _get_summary(ha: HomeAssistant, hue: PhilipsHue) -> str:
    """Get a summary of all smart home devices."""
    lines = ["🏠 Smart Home Status:"]
    lines.append("─" * 40)

    if ha:
        try:
            lights   = ha.get_all_lights()
            switches = ha.get_all_switches()
            on_lights  = [l for l in lights   if l["state"] == "on"]
            on_switches = [s for s in switches if s["state"] == "on"]

            lines.append(f"💡 Lights:   {len(on_lights)}/{len(lights)} on")
            lines.append(f"🔌 Switches: {len(on_switches)}/{len(switches)} on")

            if on_lights:
                lines.append("\nLights ON:")
                for l in on_lights[:5]:
                    lines.append(f"  • {l['name']}")
                if len(on_lights) > 5:
                    lines.append(f"  ... and {len(on_lights) - 5} more")

        except Exception as e:
            lines.append(f"Home Assistant error: {e}")

    if hue:
        try:
            all_lights = hue.get_all_lights()
            on_count   = sum(
                1 for l in all_lights.values()
                if l["state"]["on"]
            )
            lines.append(f"\n💡 Hue: {on_count}/{len(all_lights)} lights on")
        except Exception as e:
            lines.append(f"Hue error: {e}")

    return "\n".join(lines)