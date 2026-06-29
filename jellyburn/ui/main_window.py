import json
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Pango
import requests

from ..api import JellyfinClient, track_artist
from ..burner import BurnDialog
from ..config import (
    CD_MAX_SECONDS, load_config, save_config,
    check_dependencies, seconds_to_mmss,
)
from ..player import Player
from .mini_player import MiniPlayer
from .settings_dialog import SettingsDialog


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(title="Jellyburn", default_width=900, default_height=650, **kwargs)
        self.config = load_config()
        self.client = None
        self.player = Player()
        self._current_track = None
        self.playlist_tracks = []
        self._ignore_store_signals = False
        self._build_ui()
        self._apply_css()

        self.mini = MiniPlayer(
            self.player,
            on_play=self._play_selected,
            on_stop=self._stop_playback,
        )
        self.connect("delete-event", self._on_close)

        if self.config.get("server_url"):
            self._connect()

    def _on_close(self, *_):
        self.player.stop()
        self.mini.destroy()

    def _apply_css(self):
        css = """
        window, .main-box {
            background-color: #12121a;
            color: #d8d8e0;
        }
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
        searchentry {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            border-radius: 4px;
            color: #d8d8e0;
            padding: 4px 8px;
        }
        searchentry:focus { border-color: #e94560; }
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
            letter-spacing: 0.05em;
            padding: 3px 6px;
        }
        separator { background-color: #222236; }
        .lib-status {
            font-size: 11px;
            color: #6060a0;
            padding: 2px 6px;
        }
        .panel-right {
            background-color: #16162a;
            border-left: 1px solid #222236;
        }
        .panel-right treeview { background-color: #16162a; }
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
        .add-btn {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            color: #9090b0;
            font-size: 12px;
        }
        .add-btn:hover { border-color: #e94560; color: #e94560; }
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
        scale.playback trough {
            background-color: #2a2a40;
            min-height: 4px;
            border-radius: 2px;
        }
        scale.playback highlight {
            background-color: #e94560;
            min-height: 4px;
            border-radius: 2px;
        }
        scale.playback slider {
            background-color: #e94560;
            border: none;
            border-radius: 50%;
            min-width: 12px;
            min-height: 12px;
        }
        scale.playback slider:hover {
            background-color: #ff6080;
        }
        .art-placeholder {
            background-color: #1e1e30;
            border: 1px solid #2a2a40;
            border-radius: 3px;
            color: #3a3a60;
            font-size: 32px;
        }
        dialog { background-color: #1a1a2e; }
        dialog .dialog-action-area button { font-size: 12px; }
        .mini-player {
            background-color: #1a1a2e;
            border: 1px solid #222236;
        }
        paned separator {
            background-color: #222236;
            min-width: 1px;
            min-height: 1px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Jellyburn")
        header.set_subtitle("Jellyfin → CD")
        self.set_titlebar(header)

        btn_settings = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        btn_settings.set_tooltip_text("Einstellungen")
        btn_settings.connect("clicked", self._open_settings)
        header.pack_end(btn_settings)

        btn_mini = Gtk.Button.new_from_icon_name("view-restore-symbolic", Gtk.IconSize.BUTTON)
        btn_mini.set_tooltip_text("Mini-Player")
        btn_mini.connect("clicked", self._toggle_mini)
        header.pack_end(btn_mini)

        btn_connect = Gtk.Button.new_from_icon_name("network-transmit-receive-symbolic", Gtk.IconSize.BUTTON)
        btn_connect.set_tooltip_text("Neu verbinden")
        btn_connect.connect("clicked", lambda _: self._connect())
        header.pack_end(btn_connect)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(520)
        self.add(paned)

        # ── Linke Seite: Bibliothek ──
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        search_box = Gtk.Box(spacing=6, margin=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Suchen…")
        self.search_entry.connect("search-changed", self._on_search)
        search_box.pack_start(self.search_entry, True, True, 0)
        left.pack_start(search_box, False, False, 0)
        left.pack_start(Gtk.Separator(), False, False, 0)

        # ── Browser: Künstler | Alben ──
        browser_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        browser_paned.set_position(200)

        def _browser_col(store, title):
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            tv = Gtk.TreeView(model=store, headers_visible=True)
            tv.set_rules_hint(True)
            rend = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, rend, text=1)
            col.set_expand(True)
            tv.append_column(col)
            sw.add(tv)
            return sw, tv

        # cols: 0=Id  1=Name
        self.artist_store = Gtk.ListStore(str, str)
        artist_sw, self.artist_view = _browser_col(self.artist_store, "Künstler")
        self.artist_view.get_selection().connect("changed", self._on_artist_selected)

        self.album_store = Gtk.ListStore(str, str)
        album_sw, self.album_view = _browser_col(self.album_store, "Alben")
        self.album_view.get_selection().connect("changed", self._on_album_selected)

        browser_paned.pack1(artist_sw, resize=True, shrink=False)
        browser_paned.pack2(album_sw, resize=True, shrink=False)

        # ── Vertikaler Split: Browser oben, Tracks unten ──
        vpaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        vpaned.set_position(180)
        vpaned.pack1(browser_paned, resize=False, shrink=False)

        track_sw = Gtk.ScrolledWindow()
        track_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
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
        track_sw.add(self.track_view)
        vpaned.pack2(track_sw, resize=True, shrink=False)

        left.pack_start(vpaned, True, True, 0)

        self.lib_status = Gtk.Label(label="Nicht verbunden", xalign=0, margin=4)
        self.lib_status.get_style_context().add_class("lib-status")
        left.pack_start(self.lib_status, False, False, 0)

        paned.pack1(left, resize=True, shrink=False)

        # ── Rechte Seite: Playlist + Now Playing + Burn ──
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("panel-right")

        pl_header = Gtk.Box(spacing=4, margin=8)
        pl_label = Gtk.Label(xalign=0)
        pl_label.set_markup('<span font_desc="11" weight="bold" color="#9090b0">PLAYLIST</span>')
        pl_header.pack_start(pl_label, True, True, 0)

        for icon, tip, cb in [
            ("document-open-symbolic", "Playlist laden", self._load_playlist),
            ("document-save-symbolic", "Playlist speichern", self._save_playlist),
        ]:
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            pl_header.pack_start(b, False, False, 0)

        btn_clear = Gtk.Button(label="Leeren")
        btn_clear.connect("clicked", self._clear_playlist)
        pl_header.pack_start(btn_clear, False, False, 0)
        right.pack_start(pl_header, False, False, 0)

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

        sw2 = Gtk.ScrolledWindow()
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

        self.pl_view.set_reorderable(True)
        self.pl_view.connect("button-press-event", self._on_pl_right_click)
        self.pl_store.connect("row-deleted", self._sync_playlist_from_store)
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

        # ── Now Playing ──
        np_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin=8)
        np_box.get_style_context().add_class("now-playing-box")

        self.art_image = Gtk.Image()
        self.art_image.set_size_request(56, 56)
        self.art_image.get_style_context().add_class("art-placeholder")
        np_box.pack_start(self.art_image, False, False, 0)

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

        self.np_progress = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, None)
        self.np_progress.set_draw_value(False)
        self.np_progress.set_range(0, 1)
        self.np_progress.set_value(0)
        self.np_progress.get_style_context().add_class("playback")
        self.np_progress.connect("button-press-event", self._on_scrub_start)
        self.np_progress.connect("button-release-event", self._on_scrub_end)
        self._scrubbing = False
        self._total_seconds = 0

        np_info.pack_start(self.np_title, False, False, 0)
        np_info.pack_start(self.np_sub, False, False, 0)
        np_info.pack_start(np_ctrl, False, False, 0)
        np_info.pack_start(self.np_progress, False, False, 0)
        np_box.pack_start(np_info, True, True, 0)

        right.pack_start(np_box, False, False, 0)

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

    # ── Verbindung ──
    def _connect(self):
        if not self.config.get("server_url"):
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
            GLib.idle_add(self.lib_status.set_text, "Timeout – Server antwortet nicht.")
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            msg = "Ungültige Zugangsdaten." if code == 401 else f"HTTP {code}"
            GLib.idle_add(self.lib_status.set_text, msg)
        except Exception as e:
            GLib.idle_add(self.lib_status.set_text, f"Fehler: {e}")

    def _populate_tracks(self, tracks):
        self.all_tracks = tracks
        self._fill_artist_store()
        self._fill_track_store(tracks)
        self.lib_status.set_text(f"{len(tracks)} Tracks geladen")

    def _fill_artist_store(self):
        seen = {}
        self.artist_store.clear()
        self.artist_store.append(("", "Alle Künstler"))
        for t in self.all_tracks:
            for aid in t.get("ArtistIds", []):
                if aid not in seen:
                    seen[aid] = track_artist(t)
        for aid, name in sorted(seen.items(), key=lambda x: x[1].lower()):
            self.artist_store.append((aid, name))
        # Alle Künstler vorauswählen ohne Handler auszulösen
        self.artist_view.get_selection().select_path(Gtk.TreePath.new_first())

    def _fill_album_store(self, tracks):
        seen = {}
        self.album_store.clear()
        self.album_store.append(("", "Alle Alben"))
        for t in tracks:
            pid = t.get("ParentId", "")
            if pid and pid not in seen:
                seen[pid] = t.get("Album", "?")
        for pid, name in sorted(seen.items(), key=lambda x: x[1].lower()):
            self.album_store.append((pid, name))
        self.album_view.get_selection().select_path(Gtk.TreePath.new_first())

    def _on_artist_selected(self, selection):
        model, it = selection.get_selected()
        if not it:
            return
        artist_id = model[it][0]
        if artist_id == "":
            self._artist_tracks = self.all_tracks
        else:
            self._artist_tracks = [
                t for t in self.all_tracks if artist_id in t.get("ArtistIds", [])
            ]
        self._fill_album_store(self._artist_tracks)
        self._fill_track_store(self._artist_tracks)

    def _on_album_selected(self, selection):
        model, it = selection.get_selected()
        if not it:
            return
        album_id = model[it][0]
        source = getattr(self, "_artist_tracks", self.all_tracks)
        if album_id == "":
            self._fill_track_store(source)
        else:
            self._fill_track_store([t for t in source if t.get("ParentId") == album_id])

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

    # ── Suche ──
    def _on_search(self, entry):
        query = entry.get_text().lower()
        all_tracks = getattr(self, "all_tracks", [])
        if not query:
            # Browser-Selektion wiederherstellen
            sel = self.album_view.get_selection()
            model, it = sel.get_selected()
            if it:
                album_id = model[it][0]
                source = getattr(self, "_artist_tracks", all_tracks)
                self._fill_track_store(source if album_id == "" else
                                       [t for t in source if t.get("ParentId") == album_id])
            else:
                self._fill_track_store(all_tracks)
            return
        self._fill_track_store([
            t for t in all_tracks
            if query in t.get("Name", "").lower()
            or query in track_artist(t).lower()
            or query in t.get("Album", "").lower()
        ])

    # ── Wiedergabe ──
    def _on_track_activated(self, treeview, path, col):
        row = treeview.get_model()[path]
        track_id = row[0]
        if not self.client:
            return
        track = next((t for t in getattr(self, "all_tracks", []) if t["Id"] == track_id), None)
        self._play_url(self.client.get_stream_url(track_id), f"{row[2]} - {row[1]}", track=track)

    def _play_selected(self, _):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            sel2 = self.pl_view.get_selection()
            model2, paths2 = sel2.get_selected_rows()
            if paths2 and self.client:
                row = model2[paths2[0]]
                track = next((t for t in self.playlist_tracks if t["Id"] == row[0]), None)
                if track:
                    self._play_url(self.client.get_stream_url(row[0]), f"{row[3]} - {row[2]}", track=track)
            return
        row = model[paths[0]]
        if not self.client:
            return
        track = next((t for t in getattr(self, "all_tracks", []) if t["Id"] == row[0]), None)
        self._play_url(self.client.get_stream_url(row[0]), f"{row[2]} - {row[1]}", track=track)

    def _play_url(self, url, label, track=None):
        parts = label.split(" - ", 1)
        artist = parts[0] if len(parts) == 2 else ""
        title = parts[1] if len(parts) == 2 else label
        self.np_title.set_text(title)
        self.np_sub.set_text(artist)
        self.np_time.set_text("")
        self.np_progress.set_value(0)
        self.mini.set_track(title, artist)

        if track and self.client:
            threading.Thread(target=self._load_art, args=(track["Id"],), daemon=True).start()
        else:
            GLib.idle_add(self.art_image.clear)

        def on_progress(fraction, time_str, elapsed, total):
            self._total_seconds = total
            GLib.idle_add(self.np_time.set_text, time_str)
            if not self._scrubbing:
                GLib.idle_add(self.np_progress.set_range, 0, max(total, 1))
                GLib.idle_add(self.np_progress.set_value, elapsed)
            GLib.idle_add(self.mini.set_progress, elapsed, total, time_str)

        def on_error(msg):
            GLib.idle_add(self.np_title.set_text, msg)

        self.player.play(
            url, track,
            ticks_to_seconds=self.client.ticks_to_seconds if self.client else (lambda x: 0),
            on_progress=on_progress,
            on_error=on_error,
        )

    def _toggle_mini(self, _):
        if self.mini.get_visible():
            self.mini.hide()
        else:
            self.mini.show()

    def _on_scrub_start(self, widget, event):
        self._scrubbing = True

    def _on_scrub_end(self, widget, event):
        self._scrubbing = False
        if self.player.is_playing:
            self.player.seek(widget.get_value())

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
                GLib.idle_add(self.mini.set_art, pixbuf)
                return
        except Exception:
            pass
        GLib.idle_add(self.art_image.clear)
        GLib.idle_add(self.mini.set_art, None)

    def _stop_playback(self, _):
        self.player.stop()
        self.np_title.set_text("")
        self.np_sub.set_text("")
        self.np_time.set_text("")
        self.np_progress.set_value(0)
        self.art_image.clear()
        self.mini.clear()

    # ── Playlist ──
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
                self.pl_store.append([track_id, str(len(self.playlist_tracks)), row[1], row[2], row[4]])
        self._update_cd_counter()

    def _on_pl_right_click(self, widget, event):
        if event.button == 3:
            menu = Gtk.Menu()
            item_remove = Gtk.MenuItem(label="Aus Playlist entfernen")
            item_remove.connect("activate", self._remove_from_playlist)
            menu.append(item_remove)
            menu.show_all()
            menu.popup_at_pointer(event)

    def _sync_playlist_from_store(self, *_):
        if self._ignore_store_signals:
            return
        id_to_track = {t["Id"]: t for t in self.playlist_tracks}
        self.playlist_tracks = [id_to_track[row[0]] for row in self.pl_store if row[0] in id_to_track]
        self._renumber_playlist()
        self._update_cd_counter()

    def _remove_from_playlist(self, _):
        self._ignore_store_signals = True
        sel = self.pl_view.get_selection()
        model, paths = sel.get_selected_rows()
        for path in reversed(paths):
            track_id = model[path][0]
            self.playlist_tracks = [t for t in self.playlist_tracks if t["Id"] != track_id]
            model.remove(model.get_iter(path))
        self._ignore_store_signals = False
        self._renumber_playlist()
        self._update_cd_counter()

    def _renumber_playlist(self):
        for i, row in enumerate(self.pl_store):
            row[1] = str(i + 1)

    def _clear_playlist(self, _):
        self._ignore_store_signals = True
        self.playlist_tracks = []
        self.pl_store.clear()
        self._ignore_store_signals = False
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
                    dur = self.client.format_duration(track.get("RunTimeTicks", 0)) if self.client else ""
                    self.pl_store.append([track["Id"], str(len(self.playlist_tracks)),
                                          track.get("Name", ""), track_artist(track), dur])
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

    # ── Einstellungen ──
    def _open_settings(self, _):
        dlg = SettingsDialog(self, self.config)
        if dlg.run() == Gtk.ResponseType.OK:
            vals = dlg.get_values()
            self.config.update(vals)
            save_config({k: v for k, v in self.config.items() if k != "password"})
            self._connect()
        dlg.destroy()

    # ── Brennen ──
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
            dlg.format_secondary_text(
                f"Die Playlist ist {seconds_to_mmss(total_s)} lang – eine CD fasst nur 74:00. Trotzdem versuchen?"
            )
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.OK:
                return

        dlg = BurnDialog(self, self.playlist_tracks, self.client, self.config)
        dlg.run()
        dlg.destroy()
