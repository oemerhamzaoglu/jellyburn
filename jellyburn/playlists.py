import json
import os
import re

from .config import CONFIG_HOME

PLAYLIST_DIR = os.path.join(CONFIG_HOME, "jellyburn_playlists")


def sanitize_name(name):
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name


def _path_for(name):
    return os.path.join(PLAYLIST_DIR, f"{sanitize_name(name)}.json")


def list_playlists():
    if not os.path.isdir(PLAYLIST_DIR):
        return []
    names = [
        os.path.splitext(f)[0] for f in os.listdir(PLAYLIST_DIR) if f.endswith(".json")
    ]
    return sorted(names, key=str.lower)


def list_playlists_info():
    """Gibt Liste von Dicts {name, mtime, count} für alle gespeicherten Playlists zurück."""
    infos = []
    for name in list_playlists():
        path = _path_for(name)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            mtime = 0
        try:
            with open(path) as f:
                tracks = json.load(f)
            count = len(tracks) if isinstance(tracks, list) else 0
        except (OSError, json.JSONDecodeError):
            count = 0
        infos.append({"name": name, "mtime": mtime, "count": count})
    return infos


def load_playlist(name):
    path = _path_for(name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save_playlist(name, tracks):
    os.makedirs(PLAYLIST_DIR, exist_ok=True)
    with open(_path_for(name), "w") as f:
        json.dump(tracks, f, indent=2)


def delete_playlist(name):
    path = _path_for(name)
    if os.path.exists(path):
        os.remove(path)


def rename_playlist(old_name, new_name):
    old_path = _path_for(old_name)
    new_path = _path_for(new_name)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
