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

# ── Systemdeps ─────────────────────────────────────────────────────────────────
REQUIRED_TOOLS = {
    "mpv":    "Wiedergabe (mpv)",
    "ffmpeg": "Audio-Konvertierung (ffmpeg)",
    "wodim":  "CD-Brennen (wodim)",
}

def check_dependencies():
    missing = [label for cmd, label in REQUIRED_TOOLS.items()
               if subprocess.run(["which", cmd], capture_output=True).returncode != 0]
    return missing

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
    TIMEOUT = 15  # Sekunden

    def __init__(self, server_url, api_key=None, username=None, password=None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.user_id = None
        self.session = requests.Session()
        self.session.headers.update({
            "X-Emby-Authorization": f'MediaBrowser Client="Jellyburn", Device="Linux", DeviceId="jellyburn-01", Version="1.0"',
            "Content-Type": "application/json",
        })
        # apply timeout to every request automatically
        self.session.request = lambda method, url, **kw: \
            requests.Session.request(self.session, method, url,
                                     timeout=kw.pop("timeout", self.TIMEOUT), **kw)
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
        missing = check_dependencies()
        if missing:
            self._set_status("Fehlende Programme: " + ", ".join(missing))
            return
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
                    self._set_status(f"Konvertierung fehlgeschlagen: {name}\n{result.stderr.strip()[-400:]}")
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
        missing = check_dependencies()
        if missing:
            dlg = Gtk.MessageDialog(
                transient_for=win, modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Fehlende Systemabhängigkeiten",
            )
            dlg.format_secondary_text(
                "Folgende Programme wurden nicht gefunden:\n\n" +
                "\n".join(f"  • {label}" for label in missing) +
                "\n\nBitte installieren, damit alle Funktionen verfügbar sind."
            )
            dlg.run()
            dlg.destroy()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(title="Jellyburn", default_width=900, default_height=650, **kwargs)
        self.config = load_config()
        self.client = None
        self.current_player = None
        self._current_track = None
        self.playlist_tracks = []
        self._build_ui()
        self._apply_css()

        if self.config.get("server_url"):
            self._connect()

    def _apply_css(self):
        css = """
        /* ── Base ── */
        window, .main-box {
            background-color: #12121a;
            color: #d8d8e0;
        }

        /* ── HeaderBar ── */
        headerbar, headerbar * {
            background-color: #1a1a2e;
            border-bottom: 1px solid #0a0a14;
            color: #d8d8e0;
        }
        headerbar button {
            background: transparent;
            border: none;
            color: #9090b0;
            padding: 4px 6px;
        }
        headerbar button:hover { color: #e94560; }

        /* ── Search ── */
        searchentry {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            border-radius: 4px;
            color: #d8d8e0;
            padding: 4px 8px;
        }
        searchentry:focus { border-color: #e94560; }

        /* ── Library TreeView ── */
        treeview {
            background-color: #12121a;
            color: #d8d8e0;
        }
        treeview:selected {
            background-color: #e94560;
            color: #ffffff;
        }
        treeview header button {
            background-color: #1a1a2e;
            color: #7070a0;
            border-bottom: 1px solid #0a0a14;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 3px 6px;
        }

        /* ── Separators ── */
        separator { background-color: #222236; }

        /* ── Status label ── */
        .lib-status {
            font-size: 11px;
            color: #6060a0;
            padding: 2px 6px;
        }

        /* ── Playlist panel ── */
        .panel-right {
            background-color: #16162a;
            border-left: 1px solid #222236;
        }
        .panel-right treeview { background-color: #16162a; }

        /* ── CD capacity bar ── */
        .cd-counter {
            font-family: monospace;
            font-size: 12px;
            color: #7070a0;
            padding: 0 8px;
        }
        .cd-counter.over-limit { color: #e94560; font-weight: bold; }
        progressbar trough {
            background-color: #1e1e30;
            border-radius: 3px;
            min-height: 6px;
        }
        progressbar progress {
            background-color: #3dc47e;
            border-radius: 3px;
            min-height: 6px;
        }
        progressbar.cd-yellow progress { background-color: #e8a838; }
        progressbar.cd-red    progress { background-color: #e94560; }

        /* ── Buttons (general) ── */
        button {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            border-radius: 3px;
            color: #d8d8e0;
            padding: 4px 10px;
        }
        button:hover {
            background-color: #2a2a40;
            border-color: #e94560;
        }

        /* ── Add-to-playlist button ── */
        .add-btn {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            color: #9090b0;
            font-size: 12px;
        }
        .add-btn:hover { border-color: #e94560; color: #e94560; }

        /* ── Burn button ── */
        .burn-btn {
            background-color: #e94560;
            border: none;
            border-radius: 4px;
            color: #ffffff;
            font-weight: bold;
            font-size: 13px;
            padding: 8px 0;
            letter-spacing: 0.04em;
        }
        .burn-btn:hover { background-color: #c73652; }
        .burn-btn:disabled { background-color: #2a2a40; color: #5050a0; }

        /* ── Now Playing ── */
        .now-playing-box {
            background-color: #1a1a2e;
            border-top: 1px solid #222236;
            padding: 8px;
        }
        .now-playing-title {
            font-weight: bold;
            font-size: 13px;
            color: #d8d8e0;
        }
        .now-playing-sub {
            font-size: 11px;
            color: #7070a0;
        }
        progressbar.playback trough {
            background-color: #1e1e30;
            min-height: 3px;
        }
        progressbar.playback progress {
            background-color: #e94560;
            min-height: 3px;
        }

        /* ── Album art placeholder ── */
        .art-placeholder {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            border-radius: 3px;
            color: #3a3a60;
            font-size: 32px;
        }

        /* ── Dialogs ── */
        dialog { background-color: #1a1a2e; }
        dialog .dialog-action-area button { font-size: 12px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode() if isinstance(css, str) else css)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        # ── HeaderBar ──────────────────────────────────────────────────────────
        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Jellyburn")
        header.set_subtitle("Jellyfin → CD")
        self.set_titlebar(header)

        btn_settings = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        btn_settings.set_tooltip_text("Einstellungen")
        btn_settings.connect("clicked", self._open_settings)
        header.pack_end(btn_settings)

        btn_connect = Gtk.Button.new_from_icon_name("network-transmit-receive-symbolic", Gtk.IconSize.BUTTON)
        btn_connect.set_tooltip_text("Neu verbinden")
        btn_connect.connect("clicked", lambda _: self._connect())
        header.pack_end(btn_connect)

        # ── Haupt-Layout: Paned für responsives Resize ──────────────────────
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(520)
        self.add(paned)

        # ══ Linke Seite: Bibliothek ══════════════════════════════════════════
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        search_box = Gtk.Box(spacing=6, margin=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Künstler, Album oder Titel suchen…")
        self.search_entry.connect("search-changed", self._on_search)
        search_box.pack_start(self.search_entry, True, True, 0)
        left.pack_start(search_box, False, False, 0)
        left.pack_start(Gtk.Separator(), False, False, 0)

        # Track-Liste
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # cols: 0=Id  1=Titel  2=Künstler  3=Album  4=Dauer
        self.track_store = Gtk.ListStore(str, str, str, str, str)
        self.track_view = Gtk.TreeView(model=self.track_store, headers_visible=True)
        self.track_view.set_activate_on_single_click(False)
        self.track_view.set_rules_hint(True)

        for title, col, expand in [("Titel", 1, True), ("Künstler", 2, True),
                                    ("Album", 3, True), ("Länge", 4, False)]:
            rend = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, rend, text=col)
            c.set_resizable(True)
            c.set_expand(expand)
            self.track_view.append_column(c)

        self.track_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.track_view.connect("row-activated", self._on_track_activated)
        sw.add(self.track_view)
        left.pack_start(sw, True, True, 0)

        self.lib_status = Gtk.Label(label="Nicht verbunden", xalign=0, margin=4)
        self.lib_status.get_style_context().add_class("lib-status")
        left.pack_start(self.lib_status, False, False, 0)

        paned.pack1(left, resize=True, shrink=False)

        # ══ Rechte Seite: Playlist + Now Playing + Burn ══════════════════════
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("panel-right")

        # ── Playlist-Header ────────────────────────────────────────────────
        pl_header = Gtk.Box(spacing=4, margin=8)
        pl_label = Gtk.Label(xalign=0)
        pl_label.set_markup('<span font_desc="11" weight="bold" color="#9090b0">PLAYLIST</span>')
        pl_header.pack_start(pl_label, True, True, 0)

        for icon, tip, cb in [
            ("document-open-symbolic",  "Playlist laden",      self._load_playlist),
            ("document-save-symbolic",  "Playlist speichern",  self._save_playlist),
        ]:
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            pl_header.pack_start(b, False, False, 0)

        btn_clear = Gtk.Button(label="Leeren")
        btn_clear.connect("clicked", self._clear_playlist)
        pl_header.pack_start(btn_clear, False, False, 0)
        right.pack_start(pl_header, False, False, 0)

        # ── CD-Kapazitätsanzeige ───────────────────────────────────────────
        cd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                         margin_start=8, margin_end=8, margin_bottom=4, spacing=2)
        self.cd_counter = Gtk.Label(label="0:00 / 74:00", xalign=0)
        self.cd_counter.get_style_context().add_class("cd-counter")
        self.cd_bar = Gtk.ProgressBar()
        self.cd_bar.get_style_context().add_class("cd-bar")
        cd_box.pack_start(self.cd_counter, False, False, 0)
        cd_box.pack_start(self.cd_bar, False, False, 0)
        right.pack_start(cd_box, False, False, 0)
        right.pack_start(Gtk.Separator(), False, False, 0)

        # ── Playlist-Liste (mit Tracknummer) ───────────────────────────────
        sw2 = Gtk.ScrolledWindow()
        # cols: 0=Id  1=#  2=Titel  3=Künstler  4=Dauer
        self.pl_store = Gtk.ListStore(str, str, str, str, str)
        self.pl_view = Gtk.TreeView(model=self.pl_store, headers_visible=False)
        self.pl_view.set_rules_hint(True)
        self.pl_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        rend_num = Gtk.CellRendererText(xalign=1.0)
        rend_num.set_property("foreground", "#5050a0")
        col_num = Gtk.TreeViewColumn("", rend_num, text=1)
        col_num.set_min_width(28)
        self.pl_view.append_column(col_num)

        for col_idx, expand in [(2, True), (3, True), (4, False)]:
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn("", r, text=col_idx)
            c.set_expand(expand)
            self.pl_view.append_column(c)

        self.pl_view.connect("button-press-event", self._on_pl_right_click)
        sw2.add(self.pl_view)
        right.pack_start(sw2, True, True, 0)

        btn_add = Gtk.Button(label="+ Auswahl hinzufügen")
        btn_add.set_margin_start(8)
        btn_add.set_margin_end(8)
        btn_add.set_margin_top(4)
        btn_add.get_style_context().add_class("add-btn")
        btn_add.connect("clicked", self._add_selected_to_playlist)
        right.pack_start(btn_add, False, False, 0)

        right.pack_start(Gtk.Separator(), False, False, 4)

        # ── Now Playing ────────────────────────────────────────────────────
        np_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin=8)
        np_box.get_style_context().add_class("now-playing-box")

        # Album Art
        self.art_image = Gtk.Image()
        self.art_image.set_size_request(56, 56)
        self.art_image.get_style_context().add_class("art-placeholder")
        self._art_pixbuf = None
        np_box.pack_start(self.art_image, False, False, 0)

        # Titel + Fortschritt
        np_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        np_info.set_valign(Gtk.Align.CENTER)

        self.np_title = Gtk.Label(label="", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.np_title.get_style_context().add_class("now-playing-title")

        self.np_sub = Gtk.Label(label="", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.np_sub.get_style_context().add_class("now-playing-sub")

        np_ctrl = Gtk.Box(spacing=4)
        self.btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.btn_play.connect("clicked", self._play_selected)
        self.btn_stop = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic", Gtk.IconSize.BUTTON)
        self.btn_stop.connect("clicked", self._stop_playback)
        self.np_time = Gtk.Label(label="", xalign=0)
        self.np_time.get_style_context().add_class("now-playing-sub")
        np_ctrl.pack_start(self.btn_play, False, False, 0)
        np_ctrl.pack_start(self.btn_stop, False, False, 0)
        np_ctrl.pack_start(self.np_time, False, False, 4)

        self.np_progress = Gtk.ProgressBar()
        self.np_progress.get_style_context().add_class("playback")

        np_info.pack_start(self.np_title, False, False, 0)
        np_info.pack_start(self.np_sub, False, False, 0)
        np_info.pack_start(np_ctrl, False, False, 0)
        np_info.pack_start(self.np_progress, False, False, 0)
        np_box.pack_start(np_info, True, True, 0)

        # compat alias used in old play_url / stop_playback
        self.now_playing = self.np_title

        right.pack_start(np_box, False, False, 0)

        # ── Brennen-Button ─────────────────────────────────────────────────
        self.burn_btn = Gtk.Button(label="● CD BRENNEN")
        self.burn_btn.set_margin_start(8)
        self.burn_btn.set_margin_end(8)
        self.burn_btn.set_margin_bottom(8)
        self.burn_btn.set_margin_top(4)
        self.burn_btn.get_style_context().add_class("burn-btn")
        self.burn_btn.connect("clicked", self._start_burn)
        self.burn_btn.set_sensitive(False)
        right.pack_start(self.burn_btn, False, False, 0)

        paned.pack2(right, resize=False, shrink=False)

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
        except requests.exceptions.ConnectionError:
            GLib.idle_add(self.lib_status.set_text,
                          "Verbindung fehlgeschlagen – Server erreichbar?")
        except requests.exceptions.Timeout:
            GLib.idle_add(self.lib_status.set_text,
                          "Timeout – Server antwortet nicht.")
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            msg = "Ungültige Zugangsdaten." if code == 401 else f"HTTP {code}"
            GLib.idle_add(self.lib_status.set_text, msg)
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
        if not self.client:
            return
        track = next((t for t in getattr(self, "all_tracks", []) if t["Id"] == track_id), None)
        url = self.client.get_stream_url(track_id)
        self._play_url(url, f"{row[2]} - {row[1]}", track=track)

    def _play_selected(self, _):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            sel2 = self.pl_view.get_selection()
            model2, paths2 = sel2.get_selected_rows()
            if paths2 and self.client:
                row = model2[paths2[0]]
                track_id = row[0]
                track = next((t for t in self.playlist_tracks if t["Id"] == track_id), None)
                if track:
                    url = self.client.get_stream_url(track_id)
                    self._play_url(url, f"{row[3]} - {row[2]}", track=track)
            return
        row = model[paths[0]]
        if not self.client:
            return
        track = next((t for t in getattr(self, "all_tracks", []) if t["Id"] == row[0]), None)
        url = self.client.get_stream_url(row[0])
        self._play_url(url, f"{row[2]} - {row[1]}", track=track)

    def _play_url(self, url, label, track=None):
        self._stop_playback(None)
        parts = label.split(" - ", 1)
        artist = parts[0] if len(parts) == 2 else ""
        title = parts[1] if len(parts) == 2 else label
        self.np_title.set_text(title)
        self.np_sub.set_text(artist)
        self.np_time.set_text("")
        self.np_progress.set_fraction(0)
        # Album Art laden
        if track and self.client:
            threading.Thread(target=self._load_art, args=(track["Id"],), daemon=True).start()
        else:
            GLib.idle_add(self.art_image.clear)
        cmd = ["mpv", "--no-video", "--really-quiet", url]
        try:
            self.current_player = subprocess.Popen(cmd)
            self._current_track = track
            threading.Thread(target=self._track_playback, args=(track,), daemon=True).start()
        except FileNotFoundError:
            self.np_title.set_text("mpv nicht gefunden")
            self.np_sub.set_text("Bitte mpv installieren")

    def _track_playback(self, track):
        if not track:
            return
        total = self.client.ticks_to_seconds(track.get("RunTimeTicks", 0)) if self.client else 0
        start = time.monotonic()
        while self.current_player and self.current_player.poll() is None:
            elapsed = time.monotonic() - start
            fraction = min(elapsed / total, 1.0) if total else 0
            time_str = f"{seconds_to_mmss(elapsed)}" + (f" / {seconds_to_mmss(total)}" if total else "")
            GLib.idle_add(self.np_progress.set_fraction, fraction)
            GLib.idle_add(self.np_time.set_text, time_str)
            time.sleep(0.5)

    def _load_art(self, item_id):
        try:
            url = (f"{self.client.server_url}/Items/{item_id}/Images/Primary"
                   f"?fillHeight=56&fillWidth=56&quality=80&api_key={self.client.api_key}")
            resp = self.client.session.get(url, timeout=8)
            if resp.status_code == 200:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(resp.content)
                loader.close()
                pixbuf = loader.get_pixbuf()
                GLib.idle_add(self.art_image.set_from_pixbuf, pixbuf)
                return
        except Exception:
            pass
        GLib.idle_add(self.art_image.clear)

    def _stop_playback(self, _):
        if self.current_player:
            self.current_player.terminate()
            self.current_player = None
        self._current_track = None
        self.np_title.set_text("")
        self.np_sub.set_text("")
        self.np_time.set_text("")
        self.np_progress.set_fraction(0)
        self.art_image.clear()

    # ── Playlist ───────────────────────────────────────────────────────────────
    def _add_selected_to_playlist(self, _):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        for path in paths:
            row = model[path]
            track_id = row[0]
            if any(t["Id"] == track_id for t in self.playlist_tracks):
                continue
            track = next((t for t in getattr(self, "all_tracks", []) if t["Id"] == track_id), None)
            if track:
                self.playlist_tracks.append(track)
                num = str(len(self.playlist_tracks))
                self.pl_store.append([track_id, num, row[1], row[2], row[4]])
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
        for path in reversed(paths):
            track_id = model[path][0]
            self.playlist_tracks = [t for t in self.playlist_tracks if t["Id"] != track_id]
            model.remove(model.get_iter(path))
        self._renumber_playlist()
        self._update_cd_counter()

    def _renumber_playlist(self):
        for i, row in enumerate(self.pl_store):
            row[1] = str(i + 1)

    def _clear_playlist(self, _):
        self.playlist_tracks = []
        self.pl_store.clear()
        self._update_cd_counter()

    def _save_playlist(self, _):
        if not self.playlist_tracks:
            return
        dlg = Gtk.FileChooserDialog(
            title="Playlist speichern", transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dlg.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Speichern", Gtk.ResponseType.OK)
        dlg.set_current_name("playlist.json")
        dlg.set_do_overwrite_confirmation(True)
        ff = Gtk.FileFilter()
        ff.set_name("JSON-Dateien")
        ff.add_pattern("*.json")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            if not path.endswith(".json"):
                path += ".json"
            try:
                with open(path, "w") as f:
                    json.dump(self.playlist_tracks, f, indent=2)
            except OSError as e:
                self._show_error(f"Speichern fehlgeschlagen: {e}")
        dlg.destroy()

    def _load_playlist(self, _):
        dlg = Gtk.FileChooserDialog(
            title="Playlist laden", transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Öffnen", Gtk.ResponseType.OK)
        ff = Gtk.FileFilter()
        ff.set_name("JSON-Dateien")
        ff.add_pattern("*.json")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            try:
                with open(path) as f:
                    tracks = json.load(f)
                if not isinstance(tracks, list):
                    raise ValueError("Ungültiges Format")
                self._clear_playlist(None)
                for track in tracks:
                    if not isinstance(track, dict) or "Id" not in track:
                        continue
                    if any(t["Id"] == track["Id"] for t in self.playlist_tracks):
                        continue
                    self.playlist_tracks.append(track)
                    num = str(len(self.playlist_tracks))
                    dur = self.client.format_duration(track.get("RunTimeTicks", 0)) if self.client else ""
                    self.pl_store.append([track["Id"], num, track.get("Name", ""),
                                          track_artist(track), dur])
                self._update_cd_counter()
            except (OSError, json.JSONDecodeError, ValueError) as e:
                self._show_error(f"Laden fehlgeschlagen: {e}")
        dlg.destroy()

    def _show_error(self, msg):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg,
        )
        dlg.run()
        dlg.destroy()

    def _update_cd_counter(self):
        total_s = sum(
            self.client.ticks_to_seconds(t.get("RunTimeTicks", 0))
            for t in self.playlist_tracks
        ) if self.client else 0
        fraction = min(total_s / CD_MAX_SECONDS, 1.0)
        self.cd_bar.set_fraction(fraction)

        ctx = self.cd_bar.get_style_context()
        ctx.remove_class("cd-yellow")
        ctx.remove_class("cd-red")
        ctr_ctx = self.cd_counter.get_style_context()
        ctr_ctx.remove_class("over-limit")

        if total_s > CD_MAX_SECONDS:
            ctx.add_class("cd-red")
            ctr_ctx.add_class("over-limit")
            self.cd_counter.set_text(f"{seconds_to_mmss(total_s)} / 74:00  ⚠ ZU LANG")
        elif fraction > 0.85:
            ctx.add_class("cd-yellow")
            self.cd_counter.set_text(f"{seconds_to_mmss(total_s)} / 74:00")
        else:
            self.cd_counter.set_text(f"{seconds_to_mmss(total_s)} / 74:00")

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
