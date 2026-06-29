#!/usr/bin/env python3
"""
Jellyburn
- Verbindet mit Jellyfin-Server
- Musik durchsuchen und abspielen
- Playlist zusammenstellen
- Direkt auf CD brennen via wodim
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Pango
import threading
import requests
import subprocess
import tempfile
import os
import sys
import json
import time
import urllib.parse

# ── Konfiguration ──────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.expanduser("~/.config/jellyburn.json")

DEFAULT_CONFIG = {
    "server_url": "",
    "username": "",
    "api_key": "",   # alternativ zu username/password
    "cd_device": "/dev/sr0",
    "burn_speed": 4,
}

# ── Jellyfin API ───────────────────────────────────────────────────────────────
class JellyfinClient:
    def __init__(self, server_url, api_key=None, username=None, password=None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.user_id = None
        self.session = requests.Session()
        self.session.headers.update({
            "X-Emby-Authorization": f'MediaBrowser Client="Jellyburn", Device="Linux", DeviceId="jellyburn-01", Version="1.0"',
            "Content-Type": "application/json",
        })
        if api_key:
            self.session.headers["X-MediaBrowser-Token"] = api_key
        elif username and password:
            self._login(username, password)

    def _login(self, username, password):
        url = f"{self.server_url}/Users/AuthenticateByName"
        resp = self.session.post(url, json={"Username": username, "Pw": password})
        resp.raise_for_status()
        data = resp.json()
        self.api_key = data["AccessToken"]
        self.user_id = data["User"]["Id"]
        self.session.headers["X-MediaBrowser-Token"] = self.api_key

    def get_user_id(self):
        if self.user_id:
            return self.user_id
        resp = self.session.get(f"{self.server_url}/Users/Me")
        resp.raise_for_status()
        self.user_id = resp.json()["Id"]
        return self.user_id

    def search_music(self, query="", limit=100):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "Limit": limit,
            "Fields": "RunTimeTicks,AlbumArtist,Album,Path",
            "UserId": uid,
        }
        if query:
            params["SearchTerm"] = query
        resp = self.session.get(f"{self.server_url}/Items", params=params)
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_artists(self):
        uid = self.get_user_id()
        resp = self.session.get(
            f"{self.server_url}/Artists",
            params={"UserId": uid, "Recursive": "true", "Limit": 500}
        )
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_albums(self, artist_id=None):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "MusicAlbum",
            "Recursive": "true",
            "UserId": uid,
            "Limit": 500,
            "Fields": "AlbumArtist,ChildCount,RunTimeTicks",
        }
        if artist_id:
            params["AlbumArtistIds"] = artist_id
        resp = self.session.get(f"{self.server_url}/Items", params=params)
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_tracks(self, album_id=None, artist_id=None):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "UserId": uid,
            "Limit": 500,
            "Fields": "RunTimeTicks,AlbumArtist,Album,IndexNumber,ParentIndexNumber,Path",
            "SortBy": "ParentIndexNumber,IndexNumber,SortName",
        }
        if album_id:
            params["ParentId"] = album_id
        if artist_id:
            params["ArtistIds"] = artist_id
        resp = self.session.get(f"{self.server_url}/Items", params=params)
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_stream_url(self, item_id):
        uid = self.get_user_id()
        return (
            f"{self.server_url}/Audio/{item_id}/stream"
            f"?UserId={uid}&api_key={self.api_key}&AudioCodec=flac&Container=flac"
        )

    def get_download_url(self, item_id):
        return f"{self.server_url}/Items/{item_id}/Download?api_key={self.api_key}"

    def ticks_to_seconds(self, ticks):
        return ticks // 10_000_000 if ticks else 0

    def format_duration(self, ticks):
        s = self.ticks_to_seconds(ticks)
        return f"{s // 60}:{s % 60:02d}"


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────
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

def seconds_to_mmss(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"

def track_artist(track):
    return (track.get("AlbumArtist")
            or (track.get("Artists") or [""])[0]
            or "")

CD_MAX_SECONDS = 74 * 60  # 74 Minuten Standard-CD


# ── Einstellungen-Dialog ───────────────────────────────────────────────────────
class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Einstellungen", transient_for=parent, modal=True)
        self.set_default_size(420, 300)
        self.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Speichern", Gtk.ResponseType.OK)
        self.config = config

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, margin=16)
        box = self.get_content_area()
        box.pack_start(grid, True, True, 0)

        def row(label, widget, i):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
            widget.set_hexpand(True)

        self.e_url = Gtk.Entry(text=config.get("server_url", ""))
        self.e_url.set_placeholder_text("https://jellyfin.example.com")
        row("Server URL:", self.e_url, 0)

        self.e_user = Gtk.Entry(text=config.get("username", ""))
        self.e_user.set_placeholder_text("Optional wenn API-Key gesetzt")
        row("Benutzername:", self.e_user, 1)

        self.e_pass = Gtk.Entry(text="")
        self.e_pass.set_visibility(False)
        self.e_pass.set_placeholder_text("Passwort (einmalig zum Login)")
        row("Passwort:", self.e_pass, 2)

        self.e_apikey = Gtk.Entry(text=config.get("api_key", ""))
        self.e_apikey.set_placeholder_text("API-Key aus Jellyfin-Dashboard")
        row("API-Key:", self.e_apikey, 3)

        self.e_device = Gtk.Entry(text=config.get("cd_device", "/dev/sr0"))
        row("CD-Laufwerk:", self.e_device, 4)

        self.e_speed = Gtk.SpinButton.new_with_range(1, 52, 1)
        self.e_speed.set_value(config.get("burn_speed", 4))
        row("Brenngeschwindigkeit:", self.e_speed, 5)

        self.show_all()

    def get_values(self):
        return {
            "server_url": self.e_url.get_text().strip(),
            "username": self.e_user.get_text().strip(),
            "password": self.e_pass.get_text(),
            "api_key": self.e_apikey.get_text().strip(),
            "cd_device": self.e_device.get_text().strip(),
            "burn_speed": int(self.e_speed.get_value()),
        }


# ── Brenn-Dialog ───────────────────────────────────────────────────────────────
class BurnDialog(Gtk.Dialog):
    def __init__(self, parent, playlist, client, config):
        super().__init__(title="CD brennen", transient_for=parent, modal=True)
        self.set_default_size(500, 400)
        self.playlist = playlist
        self.client = client
        self.config = config
        self.cancelled = False
        self._burning = False

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        box.pack_start(Gtk.Label(label="<b>Tracks auf CD:</b>", use_markup=True, xalign=0), False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(150)
        tv = Gtk.TextView(editable=False, monospace=True)
        buf = tv.get_buffer()
        lines = "\n".join(
            f"{i+1:2}. {track_artist(t) or '?'} - {t.get('Name','?')} ({client.format_duration(t.get('RunTimeTicks',0))})"
            for i, t in enumerate(playlist)
        )
        buf.set_text(lines)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)

        self.status_label = Gtk.Label(label="Bereit zum Brennen.", xalign=0)
        self.status_label.set_line_wrap(True)
        box.pack_start(self.status_label, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        box.pack_start(self.progress, False, False, 0)

        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        btn_box.set_margin_top(4)

        self.cancel_btn = Gtk.Button(label="Abbrechen")
        self.cancel_btn.connect("clicked", self._on_cancel)
        btn_box.pack_start(self.cancel_btn, False, False, 0)

        self.burn_btn = Gtk.Button(label="Jetzt brennen")
        self.burn_btn.get_style_context().add_class("suggested-action")
        self.burn_btn.connect("clicked", self._on_burn_clicked)
        btn_box.pack_start(self.burn_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 0)
        self.show_all()

    def _on_burn_clicked(self, _):
        self.burn_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(False)
        self._burning = True
        thread = threading.Thread(target=self._burn_thread, daemon=True)
        thread.start()

    def _on_cancel(self, _):
        if self._burning:
            self.cancelled = True
        else:
            self.response(Gtk.ResponseType.CANCEL)

    def _on_burn_done(self):
        self.cancel_btn.set_label("Schließen")
        self.cancel_btn.set_sensitive(True)

    def _set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _set_progress(self, fraction, text=""):
        def _update():
            self.progress.set_fraction(fraction)
            if text:
                self.progress.set_text(text)
        GLib.idle_add(_update)

    def _burn_thread(self):
        tmpdir = tempfile.mkdtemp(prefix="jellyfin_burn_")
        wav_files = []

        try:
            total = len(self.playlist)
            for i, track in enumerate(self.playlist):
                if self.cancelled:
                    return
                name = track.get("Name", f"track_{i+1}")
                artist = track_artist(track)
                self._set_status(f"Lade: {artist} - {name} ({i+1}/{total})")
                self._set_progress(i / total / 2, f"Download {i+1}/{total}")

                # Download
                url = self.client.get_download_url(track["Id"])
                resp = self.client.session.get(url, stream=True)
                resp.raise_for_status()

                src_path = os.path.join(tmpdir, f"track_{i+1:02d}_src")
                with open(src_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)

                # Konvertieren zu WAV via ffmpeg
                wav_path = os.path.join(tmpdir, f"track_{i+1:02d}.wav")
                self._set_status(f"Konvertiere: {name}")
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", src_path, "-ar", "44100", "-ac", "2", "-f", "wav", wav_path],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    self._set_status(f"Fehler bei Konvertierung: {name}\n{result.stderr[-200:]}")
                    return
                wav_files.append(wav_path)
                os.unlink(src_path)
                self._set_progress((i + 1) / total / 2, f"Konvertiert {i+1}/{total}")

            if self.cancelled:
                return

            self._set_status("Starte Brennvorgang - bitte nicht abbrechen...")
            self._set_progress(0.5, "Brennen...")

            device = self.config.get("cd_device", "/dev/sr0")
            speed = self.config.get("burn_speed", 4)

            cmd = [
                "wodim",
                f"dev={device}",
                f"speed={speed}",
                "-v",
                "-audio",
                "-pad",
            ] + wav_files

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            output_lines = []
            for line in proc.stdout:
                line = line.strip()
                output_lines.append(line)
                if "%" in line or "Track" in line or "Writing" in line:
                    self._set_status(line)

            proc.wait()
            if proc.returncode == 0:
                self._set_status("CD erfolgreich gebrannt!")
                self._set_progress(1.0, "Fertig!")
            else:
                last = "\n".join(output_lines[-5:])
                self._set_status(f"Brenner-Fehler (Code {proc.returncode}):\n{last}")

        except Exception as e:
            self._set_status(f"Fehler: {e}")
        finally:
            for f in wav_files:
                try:
                    os.unlink(f)
                except:
                    pass
            try:
                os.rmdir(tmpdir)
            except:
                pass
            GLib.idle_add(self._on_burn_done)


# ── Haupt-App ──────────────────────────────────────────────────────────────────
class JellyburnApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="de.linumed.jellyfinburner")

    def do_activate(self):
        win = MainWindow(application=self)
        win.show_all()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(title="Jellyburn", default_width=900, default_height=650, **kwargs)
        self.config = load_config()
        self.client = None
        self.current_player = None
        self.playlist_tracks = []  # Liste der Track-Dicts in der Playlist
        self._build_ui()
        self._apply_css()

        if self.config.get("server_url"):
            self._connect()

    def _apply_css(self):
        css = b"""
        .sidebar { background-color: #1a1a2e; color: #e0e0e0; }
        .playlist-area { background-color: #16213e; }
        .track-row:hover { background-color: #0f3460; }
        .burn-btn { background-color: #e94560; color: white; border-radius: 4px; }
        .burn-btn:hover { background-color: #c73652; }
        .header-bar { background-color: #0f3460; }
        label.track-title { font-weight: bold; }
        .cd-counter { font-family: monospace; font-size: 14px; color: #e94560; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        # Header
        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Jellyburn")
        self.set_titlebar(header)

        btn_settings = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        btn_settings.set_tooltip_text("Einstellungen")
        btn_settings.connect("clicked", self._open_settings)
        header.pack_end(btn_settings)

        btn_connect = Gtk.Button.new_from_icon_name("network-transmit-receive-symbolic", Gtk.IconSize.BUTTON)
        btn_connect.set_tooltip_text("Neu verbinden")
        btn_connect.connect("clicked", lambda _: self._connect())
        header.pack_end(btn_connect)

        # Haupt-Layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(main_box)

        # Linke Seite: Bibliothek
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=420)
        main_box.pack_start(left, True, True, 0)

        # Suche
        search_box = Gtk.Box(spacing=6, margin=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Künstler, Album oder Titel suchen...")
        self.search_entry.connect("search-changed", self._on_search)
        search_box.pack_start(self.search_entry, True, True, 0)
        left.pack_start(search_box, False, False, 0)

        left.pack_start(Gtk.Separator(), False, False, 0)

        # Track-Liste
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.track_store = Gtk.ListStore(str, str, str, str, str)
        # Spalten: Id, Titel, Künstler, Album, Dauer

        self.track_view = Gtk.TreeView(model=self.track_store, headers_visible=True)
        self.track_view.set_activate_on_single_click(False)

        for i, (title, col) in enumerate([("Titel", 1), ("Künstler", 2), ("Album", 3), ("Länge", 4)]):
            renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            col_obj = Gtk.TreeViewColumn(title, renderer, text=col)
            col_obj.set_resizable(True)
            if i < 3:
                col_obj.set_expand(True)
            self.track_view.append_column(col_obj)

        self.track_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.track_view.connect("row-activated", self._on_track_activated)

        sw.add(self.track_view)
        left.pack_start(sw, True, True, 0)

        # Statusleiste Bibliothek
        self.lib_status = Gtk.Label(label="Nicht verbunden", xalign=0, margin=4)
        left.pack_start(self.lib_status, False, False, 0)

        # Trennlinie
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        # Rechte Seite: Playlist + Player
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=360)
        main_box.pack_start(right, False, False, 0)

        # Playlist-Header
        pl_header = Gtk.Box(spacing=6, margin=8)
        pl_label = Gtk.Label(label="<b>Playlist</b>", use_markup=True, xalign=0)
        pl_header.pack_start(pl_label, True, True, 0)

        btn_clear = Gtk.Button(label="Leeren")
        btn_clear.connect("clicked", self._clear_playlist)
        pl_header.pack_start(btn_clear, False, False, 0)

        right.pack_start(pl_header, False, False, 0)

        # CD-Kapazitatsanzeige
        self.cd_counter = Gtk.Label(label="0:00 / 74:00", xalign=0, margin_start=8)
        self.cd_counter.get_style_context().add_class("cd-counter")
        self.cd_bar = Gtk.ProgressBar()
        self.cd_bar.set_margin_start(8)
        self.cd_bar.set_margin_end(8)
        right.pack_start(self.cd_counter, False, False, 0)
        right.pack_start(self.cd_bar, False, False, 2)

        right.pack_start(Gtk.Separator(), False, False, 0)

        # Playlist-Liste
        sw2 = Gtk.ScrolledWindow()
        self.pl_store = Gtk.ListStore(str, str, str, str)
        # Id, Titel, Künstler, Dauer

        self.pl_view = Gtk.TreeView(model=self.pl_store, headers_visible=False)
        self.pl_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        for i, col in enumerate([1, 2, 3]):
            renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn("", renderer, text=col)
            if i < 2:
                c.set_expand(True)
            self.pl_view.append_column(c)

        # Kontextmenu Playlist
        self.pl_view.connect("button-press-event", self._on_pl_right_click)
        sw2.add(self.pl_view)
        right.pack_start(sw2, True, True, 0)

        # "Zur Playlist hinzufügen" Button
        btn_add = Gtk.Button(label="+ Auswahl zur Playlist hinzufügen")
        btn_add.set_margin_start(8)
        btn_add.set_margin_end(8)
        btn_add.set_margin_top(4)
        btn_add.connect("clicked", self._add_selected_to_playlist)
        right.pack_start(btn_add, False, False, 0)

        right.pack_start(Gtk.Separator(), False, False, 4)

        # Player Controls
        player_box = Gtk.Box(spacing=4, margin=8)
        self.btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.btn_play.connect("clicked", self._play_selected)
        self.btn_stop = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic", Gtk.IconSize.BUTTON)
        self.btn_stop.connect("clicked", self._stop_playback)
        self.now_playing = Gtk.Label(label="", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        player_box.pack_start(self.btn_play, False, False, 0)
        player_box.pack_start(self.btn_stop, False, False, 0)
        player_box.pack_start(self.now_playing, True, True, 0)
        right.pack_start(player_box, False, False, 0)

        # Brennen-Button
        self.burn_btn = Gtk.Button(label="CD brennen")
        self.burn_btn.set_margin_start(8)
        self.burn_btn.set_margin_end(8)
        self.burn_btn.set_margin_bottom(8)
        self.burn_btn.get_style_context().add_class("burn-btn")
        self.burn_btn.connect("clicked", self._start_burn)
        self.burn_btn.set_sensitive(False)
        right.pack_start(self.burn_btn, False, False, 0)

    # ── Verbindung ─────────────────────────────────────────────────────────────
    def _connect(self):
        cfg = self.config
        if not cfg.get("server_url"):
            self._open_settings(None)
            return

        self.lib_status.set_text("Verbinde...")
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        try:
            self.client = JellyfinClient(
                server_url=self.config["server_url"],
                api_key=self.config.get("api_key") or None,
                username=self.config.get("username") or None,
                password=self.config.get("password") or None,
            )
            tracks = self.client.search_music(limit=500)
            GLib.idle_add(self._populate_tracks, tracks)
        except Exception as e:
            GLib.idle_add(self.lib_status.set_text, f"Fehler: {e}")

    def _populate_tracks(self, tracks):
        self.all_tracks = tracks
        self._fill_track_store(tracks)
        self.lib_status.set_text(f"{len(tracks)} Tracks geladen")

    def _fill_track_store(self, tracks):
        self.track_store.clear()
        for t in tracks:
            self.track_store.append([
                t["Id"],
                t.get("Name", ""),
                track_artist(t),
                t.get("Album", ""),
                self.client.format_duration(t.get("RunTimeTicks", 0)) if self.client else "",
            ])

    # ── Suche ──────────────────────────────────────────────────────────────────
    def _on_search(self, entry):
        query = entry.get_text().lower()
        if not query:
            self._fill_track_store(getattr(self, "all_tracks", []))
            return
        filtered = [
            t for t in getattr(self, "all_tracks", [])
            if query in t.get("Name", "").lower()
            or query in track_artist(t).lower()
            or query in t.get("Album", "").lower()
        ]
        self._fill_track_store(filtered)

    # ── Track abspielen ────────────────────────────────────────────────────────
    def _on_track_activated(self, treeview, path, col):
        model = treeview.get_model()
        row = model[path]
        track_id = row[0]
        name = row[1]
        artist = row[2]
        if not self.client:
            return
        url = self.client.get_stream_url(track_id)
        self._play_url(url, f"{artist} - {name}")

    def _play_selected(self, _):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            # aus Playlist spielen
            sel2 = self.pl_view.get_selection()
            model2, paths2 = sel2.get_selected_rows()
            if paths2 and self.client:
                row = model2[paths2[0]]
                track_id = row[0]
                # Finde Original-Track
                track = next((t for t in self.playlist_tracks if t["Id"] == track_id), None)
                if track:
                    url = self.client.get_stream_url(track_id)
                    self._play_url(url, f"{row[2]} - {row[1]}")
            return
        row = model[paths[0]]
        if not self.client:
            return
        url = self.client.get_stream_url(row[0])
        self._play_url(url, f"{row[2]} - {row[1]}")

    def _play_url(self, url, label):
        self._stop_playback(None)
        self.now_playing.set_text(f"▶ {label}")
        cmd = ["mpv", "--no-video", "--really-quiet", url]
        try:
            self.current_player = subprocess.Popen(cmd)
        except FileNotFoundError:
            self.now_playing.set_text("mpv nicht gefunden - bitte installieren")

    def _stop_playback(self, _):
        if self.current_player:
            self.current_player.terminate()
            self.current_player = None
        self.now_playing.set_text("")

    # ── Playlist ───────────────────────────────────────────────────────────────
    def _add_selected_to_playlist(self, _):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        for path in paths:
            row = model[path]
            track_id = row[0]
            # Duplikat-Check
            if any(t["Id"] == track_id for t in self.playlist_tracks):
                continue
            # Original-Track-Dict finden
            track = next((t for t in getattr(self, "all_tracks", []) if t["Id"] == track_id), None)
            if track:
                self.playlist_tracks.append(track)
                self.pl_store.append([
                    track_id,
                    row[1],
                    row[2],
                    row[4],
                ])
        self._update_cd_counter()

    def _on_track_activated_pl(self, treeview, path, col):
        pass  # Doppelklick in Playlist = abspielen (optional erweiterbar)

    def _on_pl_right_click(self, widget, event):
        if event.button == 3:
            menu = Gtk.Menu()
            item_remove = Gtk.MenuItem(label="Aus Playlist entfernen")
            item_remove.connect("activate", self._remove_from_playlist)
            menu.append(item_remove)
            menu.show_all()
            menu.popup_at_pointer(event)

    def _remove_from_playlist(self, _):
        sel = self.pl_view.get_selection()
        model, paths = sel.get_selected_rows()
        # Rueckwarts loeschen um Indizes zu erhalten
        for path in reversed(paths):
            row = model[path]
            track_id = row[0]
            self.playlist_tracks = [t for t in self.playlist_tracks if t["Id"] != track_id]
            model.remove(model.get_iter(path))
        self._update_cd_counter()

    def _clear_playlist(self, _):
        self.playlist_tracks = []
        self.pl_store.clear()
        self._update_cd_counter()

    def _update_cd_counter(self):
        total_s = sum(
            self.client.ticks_to_seconds(t.get("RunTimeTicks", 0))
            for t in self.playlist_tracks
        ) if self.client else 0
        fraction = min(total_s / CD_MAX_SECONDS, 1.0)
        self.cd_counter.set_text(f"{seconds_to_mmss(total_s)} / 74:00")
        self.cd_bar.set_fraction(fraction)
        if total_s > CD_MAX_SECONDS:
            self.cd_counter.set_markup(f'<span color="red"><b>{seconds_to_mmss(total_s)} / 74:00 - ZU LANG!</b></span>')
        self.burn_btn.set_sensitive(len(self.playlist_tracks) > 0)

    # ── Einstellungen ──────────────────────────────────────────────────────────
    def _open_settings(self, _):
        dlg = SettingsDialog(self, self.config)
        if dlg.run() == Gtk.ResponseType.OK:
            vals = dlg.get_values()
            self.config.update(vals)
            save_config({k: v for k, v in self.config.items() if k != "password"})
            self._connect()
        dlg.destroy()

    # ── Brennen ────────────────────────────────────────────────────────────────
    def _start_burn(self, _):
        if not self.playlist_tracks:
            return
        total_s = sum(self.client.ticks_to_seconds(t.get("RunTimeTicks", 0)) for t in self.playlist_tracks)
        if total_s > CD_MAX_SECONDS:
            dlg = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="Playlist zu lang!",
            )
            dlg.format_secondary_text(f"Die Playlist ist {seconds_to_mmss(total_s)} lang - eine CD fasst nur 74:00. Trotzdem versuchen?")
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.OK:
                return

        dlg = BurnDialog(self, self.playlist_tracks, self.client, self.config)
        dlg.run()
        dlg.destroy()


# ── Einstiegspunkt ─────────────────────────────────────────────────────────────
def main():
    app = JellyburnApp()
    app.run(sys.argv)

if __name__ == "__main__":
    main()
