import hashlib
import json
import os
import subprocess

REQUIRED_TOOLS = {
    "mpv": "Wiedergabe (mpv)",
    "ffmpeg": "Audio-Konvertierung (ffmpeg)",
}

CONFIG_FILE = os.path.expanduser("~/.config/jellyburn.json")

DEFAULT_CONFIG = {
    "server_url": "",
    "username": "",
    "api_key": "",
    "cd_device": "/dev/sr0",
    "burn_speed": 4,
    "cd_text": True,
    "mp3_auto_switch": False,
    "eq_enabled": False,
    "eq_bands": [0.0] * 10,
    "theme": "dark",
}

CD_MAX_SECONDS = 74 * 60
CD_DATA_MAX_BYTES = 700_000_000
MP3_BITRATE_KBPS = 192


def get_burn_tool():
    """Gibt 'cdrskin' oder 'wodim' zurück, je nachdem was installiert ist."""
    for cmd in ("cdrskin", "wodim"):
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            return cmd
    return None


def get_iso_tool():
    """Gibt das erste verfügbare ISO-Erstellungswerkzeug zurück."""
    for cmd in ("xorriso", "genisoimage", "mkisofs"):
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            return cmd
    return None


def check_dependencies():
    missing = [
        label
        for cmd, label in REQUIRED_TOOLS.items()
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0
    ]
    if get_burn_tool() is None:
        missing.append("CD-Brennen (cdrskin oder wodim)")
    return missing


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


CACHE_DIR = os.path.expanduser("~/.cache/jellyburn")


def _cache_path(server_url):
    h = hashlib.md5(server_url.encode()).hexdigest()[:10]
    return os.path.join(CACHE_DIR, f"library_{h}.json")


def load_library_cache(server_url):
    path = _cache_path(server_url)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return None


def save_library_cache(server_url, tracks):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(server_url), "w") as f:
        json.dump(tracks, f)


def detect_cd_devices():
    """Gibt Liste von (dev_path, label) für alle erkannten optischen Laufwerke zurück."""
    import glob

    devices = []
    for sr in sorted(glob.glob("/sys/block/sr*")):
        name = os.path.basename(sr)
        dev = f"/dev/{name}"
        try:
            vendor = open(f"{sr}/device/vendor").read().strip()
            model = open(f"{sr}/device/model").read().strip()
            label = f"{vendor} {model}  ({dev})"
        except OSError:
            label = dev
        devices.append((dev, label))
    return devices
