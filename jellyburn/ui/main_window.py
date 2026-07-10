import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Pango
import requests

from ..api import JellyfinClient, track_artist
from ..config import (
    CD_MAX_SECONDS,
    CD_DATA_MAX_BYTES,
    MP3_BITRATE_KBPS,
    load_config,
    save_config,
    load_library_cache,
    save_library_cache,
)
from ..i18n import _
from ..player import Player
from ..util import seconds_to_mmss
from .burn_dialog import BurnDialog
from .dialogs import show_error
from .mini_player import MiniPlayer
from .now_playing import NowPlayingBox
from .playlist_pane import PlaylistPane
from .settings_dialog import SettingsDialog
from .style import ThemeManager


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(
            title="Jellyburn", default_width=900, default_height=650, **kwargs
        )
        self.config = load_config()
        self.client = None
        self.player = Player()
        self.player.set_eq(
            self.config.get("eq_bands", [0.0] * 10),
            self.config.get("eq_enabled", False),
        )
        self._track_sort_col = None
        self._track_sort_order = Gtk.SortType.ASCENDING
        self._connecting = False
        self._connect_generation = 0
        self._filter_artist = ""
        self._filter_album = ""
        self._filter_query = ""
        self._browser_loading = False
        self._build_ui()
        self.theme = ThemeManager(self.get_screen(), self.config)

        self.mini = MiniPlayer(
            self.player,
            on_play=self.now_playing.toggle_play_pause,
            on_stop=self.now_playing.stop,
            on_restore=self._restore_from_mini,
        )
        self.now_playing.set_mini(self.mini)
        self.connect("delete-event", self._on_close)

        if self.config.get("server_url"):
            self._connect()

    def _on_close(self, *_):
        self.playlist.autosave()
        self.player.stop()
        self.mini.destroy()

    def _build_ui(self):
        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Jellyburn")
        header.set_subtitle("")
        self.set_titlebar(header)
        self._load_icon()

        btn_settings = Gtk.Button.new_from_icon_name(
            "preferences-system-symbolic", Gtk.IconSize.BUTTON
        )
        btn_settings.set_tooltip_text(_("Settings"))
        btn_settings.connect("clicked", self._open_settings)
        header.pack_end(btn_settings)

        btn_mini = Gtk.Button.new_from_icon_name(
            "view-restore-symbolic", Gtk.IconSize.BUTTON
        )
        btn_mini.set_tooltip_text(_("Mini Player"))
        btn_mini.connect("clicked", self._toggle_mini)
        header.pack_end(btn_mini)

        btn_connect = Gtk.Button.new_from_icon_name(
            "network-transmit-receive-symbolic", Gtk.IconSize.BUTTON
        )
        btn_connect.set_tooltip_text(_("Reconnect"))
        btn_connect.connect("clicked", lambda _: self._connect())
        header.pack_end(btn_connect)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(520)
        self.add(paned)

        # ── Linke Seite: Bibliothek ──
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        search_box = Gtk.Box(spacing=6, margin=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Search…"))
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
            col.set_sort_column_id(1)
            tv.append_column(col)
            sw.add(tv)
            return sw, tv

        # cols: 0=Id  1=Name
        self.artist_store = Gtk.ListStore(str, str)
        artist_sw, self.artist_view = _browser_col(self.artist_store, _("Artists"))
        self.artist_view.get_selection().connect("changed", self._on_artist_selected)

        self.album_store = Gtk.ListStore(str, str)
        album_sw, self.album_view = _browser_col(self.album_store, _("Albums"))
        self.album_view.get_selection().connect("changed", self._on_album_selected)
        self.album_view.connect("button-press-event", self._on_album_right_click)

        browser_paned.pack1(artist_sw, resize=True, shrink=False)
        browser_paned.pack2(album_sw, resize=True, shrink=False)

        # ── Vertikaler Split: Browser oben, Tracks unten ──
        vpaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        vpaned.set_position(180)
        vpaned.pack1(browser_paned, resize=False, shrink=False)

        track_sw = Gtk.ScrolledWindow()
        track_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # cols: 0=Id  1=Nr  2=Titel  3=Künstler  4=Album  5=Dauer  6=ArtistKey  7=ParentId
        self.track_store, self._track_filter = self._create_track_store()
        self.track_view = Gtk.TreeView(model=self._track_filter, headers_visible=True)
        self.track_view.set_activate_on_single_click(False)
        self.track_view.set_rules_hint(True)

        for title, col, expand in [
            ("#", 1, False),
            (_("Title"), 2, True),
            (_("Artist"), 3, True),
            (_("Album"), 4, True),
            (_("Length"), 5, False),
        ]:
            rend = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            if title == "#":
                rend.set_property("xalign", 1.0)
            c = Gtk.TreeViewColumn(title, rend, text=col)
            c.set_resizable(True)
            c.set_expand(expand)
            c.set_clickable(True)
            c.connect("clicked", self._on_track_column_clicked, col)
            self.track_view.append_column(c)

        self.track_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.track_view.connect("row-activated", self._on_track_activated)
        self.track_view.connect("button-press-event", self._on_track_right_click)
        track_sw.add(self.track_view)
        vpaned.pack2(track_sw, resize=True, shrink=False)

        left.pack_start(vpaned, True, True, 0)

        self.load_bar = Gtk.ProgressBar()
        self.load_bar.set_no_show_all(True)
        left.pack_start(self.load_bar, False, False, 0)

        self.lib_status = Gtk.Label(label=_("Not connected"), xalign=0, margin=4)
        self.lib_status.get_style_context().add_class("lib-status")
        left.pack_start(self.lib_status, False, False, 0)

        paned.pack1(left, resize=True, shrink=False)

        # ── Rechte Seite: Playlist + Now Playing + Burn ──
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("panel-right")

        self.playlist = PlaylistPane(
            self.config,
            get_client=lambda: self.client,
            get_library_selection=self._get_library_selection,
            on_burn_requested=lambda: self._start_burn(None),
        )
        right.pack_start(self.playlist, True, True, 0)

        right.pack_start(Gtk.Separator(), False, False, 4)

        # ── Now Playing ──
        self.now_playing = NowPlayingBox(
            self.player,
            self.config,
            get_client=lambda: self.client,
            get_selection=self._get_play_selection,
        )
        right.pack_start(self.now_playing, False, False, 0)

        paned.pack2(right, resize=False, shrink=False)

    def _load_icon(self):
        import os

        icon_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "icons", "jellyburn.svg")
        )
        if os.path.exists(icon_path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 64, 64)
                self.set_icon(pb)
            except Exception:
                pass

    # ── Verbindung ──
    def _connect(self):
        if not self.config.get("server_url"):
            self._open_settings(None)
            return
        if self._connecting:
            return
        self._connecting = True
        self._connect_generation += 1
        self._reset_track_store()
        self.artist_store.clear()
        self.album_store.clear()
        self.load_bar.set_fraction(0)
        self.load_bar.show()
        self.lib_status.set_text(_("Connecting…"))
        threading.Thread(
            target=self._connect_thread, args=(self._connect_generation,), daemon=True
        ).start()

    def _connect_thread(self, gen):
        server_url = self.config["server_url"]
        try:
            self.client = JellyfinClient(
                server_url=server_url,
                api_key=self.config.get("api_key") or None,
                username=self.config.get("username") or None,
                password=self.config.get("password") or None,
            )

            # A username/password login yields a fresh api_key - persist
            # it immediately so any later reconnect (e.g. triggered by an
            # unrelated settings change) doesn't fall back to whatever
            # (possibly stale/absent) api_key was in config before. This
            # must happen regardless of the cached/uncached path below.
            if self.client.api_key and self.client.api_key != self.config.get(
                "api_key"
            ):
                self.config["api_key"] = self.client.api_key
                save_config({k: v for k, v in self.config.items() if k != "password"})

            cached = load_library_cache(server_url)
            if cached:
                GLib.idle_add(self._apply_cache, cached)
                # Hintergrund-Refresh ohne Fortschrittsbalken
                fresh = self.client.search_music()
                GLib.idle_add(self._apply_refresh, fresh)
            else:
                # Kein Cache: seitenweise laden mit Fortschrittsbalken
                all_tracks = []

                def on_page(page, loaded, total):
                    all_tracks.extend(page)
                    fraction = loaded / total if total else 0
                    GLib.idle_add(
                        self._on_load_page, list(page), loaded, total, fraction
                    )

                self.client.search_music(on_page=on_page)
                GLib.idle_add(self._populate_tracks, all_tracks)

        except requests.exceptions.ConnectionError:
            GLib.idle_add(self.load_bar.hide)
            GLib.idle_add(
                self.lib_status.set_text,
                _("Connection failed – is the server reachable?"),
            )
        except requests.exceptions.Timeout:
            GLib.idle_add(self.load_bar.hide)
            GLib.idle_add(
                self.lib_status.set_text, _("Timeout – server not responding.")
            )
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            msg = _("Invalid credentials.") if code == 401 else f"HTTP {code}"
            GLib.idle_add(self.load_bar.hide)
            GLib.idle_add(self.lib_status.set_text, msg)
        except Exception as e:
            GLib.idle_add(self.load_bar.hide)
            GLib.idle_add(self.lib_status.set_text, _("Error: {error}").format(error=e))
        finally:
            GLib.idle_add(self._on_connect_thread_done)

    def _on_connect_thread_done(self):
        self._connecting = False

    def _apply_cache(self, tracks):
        self.all_tracks = tracks
        for t in tracks:
            artist = track_artist(t)
            self.track_store.append(
                [
                    t["Id"],
                    str(t.get("IndexNumber") or ""),
                    t.get("Name", ""),
                    artist,
                    t.get("Album", ""),
                    t.get("_dur", ""),
                    artist,
                    t.get("ParentId", ""),
                ]
            )
        self.load_bar.hide()
        self.lib_status.set_text(
            _("{n} tracks (cache) – refreshing…").format(n=len(tracks))
        )
        # Nächster Idle-Zyklus: GTK hat den Store dann vollständig verarbeitet
        GLib.idle_add(self._fill_artist_store)

    def _apply_refresh(self, fresh_tracks):
        existing_ids = {t["Id"] for t in self.all_tracks}
        fresh_ids = {t["Id"] for t in fresh_tracks}

        new_tracks = [t for t in fresh_tracks if t["Id"] not in existing_ids]
        removed_ids = existing_ids - fresh_ids

        if new_tracks:
            for t in new_tracks:
                artist = track_artist(t)
                dur = (
                    self.client.format_duration(t.get("RunTimeTicks", 0))
                    if self.client
                    else ""
                )
                t["_dur"] = dur
                self.all_tracks.append(t)
                self.track_store.append(
                    [
                        t["Id"],
                        str(t.get("IndexNumber") or ""),
                        t.get("Name", ""),
                        artist,
                        t.get("Album", ""),
                        dur,
                        artist,
                        t.get("ParentId", ""),
                    ]
                )

        if removed_ids:
            self.all_tracks = [t for t in self.all_tracks if t["Id"] not in removed_ids]
            it = self.track_store.get_iter_first()
            while it:
                if self.track_store[it][0] in removed_ids:
                    it = self.track_store.remove(it)
                else:
                    it = self.track_store.iter_next(it)

        self._fill_artist_store()

        save_library_cache(self.config["server_url"], self.all_tracks)

        changes = []
        if new_tracks:
            changes.append(f"+{len(new_tracks)} {_('new')}")
        if removed_ids:
            changes.append(f"-{len(removed_ids)} {_('removed')}")
        suffix = f" ({', '.join(changes)})" if changes else ""
        self.lib_status.set_text(f"{len(self.all_tracks)} tracks{suffix}")

    def _on_load_page(self, page, loaded, total, fraction):
        self.load_bar.set_fraction(fraction)
        self.lib_status.set_text(
            _("Loading… {loaded} / {total}").format(loaded=loaded, total=total)
        )
        if not self.client:
            return
        for t in page:
            artist = track_artist(t)
            dur = self.client.format_duration(t.get("RunTimeTicks", 0))
            t["_dur"] = dur
            self.track_store.append(
                [
                    t["Id"],
                    str(t.get("IndexNumber") or ""),
                    t.get("Name", ""),
                    artist,
                    t.get("Album", ""),
                    dur,
                    artist,
                    t.get("ParentId", ""),
                ]
            )

    def _populate_tracks(self, tracks):
        self.all_tracks = tracks
        self.load_bar.hide()
        # _dur für Cache-Kompatibilität setzen
        for t in tracks:
            t["_dur"] = self.client.format_duration(t.get("RunTimeTicks", 0))
        save_library_cache(self.config["server_url"], tracks)
        self._fill_artist_store()
        self.lib_status.set_text(_("{n} tracks loaded").format(n=len(tracks)))

    def _track_visible(self, model, it, _data):
        if self._filter_query:
            q = self._filter_query
            return (
                q in model[it][2].lower()
                or q in model[it][3].lower()
                or q in model[it][4].lower()
            )
        if self._filter_artist and model[it][6] != self._filter_artist:
            return False
        if self._filter_album and model[it][7] != self._filter_album:
            return False
        return True

    def _create_track_store(self):
        store = Gtk.ListStore(str, str, str, str, str, str, str, str)
        store.set_sort_func(1, self._sort_track_number, None)
        store.set_sort_func(5, self._sort_duration, None)
        track_filter = store.filter_new()
        track_filter.set_visible_func(self._track_visible)
        return store, track_filter

    def _reset_track_store(self):
        # Recreate store+filter from scratch rather than calling
        # store.clear(): once a custom sort_func has been activated via
        # column-header clicks, clearing a large (tens of thousands of
        # rows) sorted ListStore through an attached TreeModelFilter
        # becomes catastrophically slow (minutes, effectively hangs) -
        # a fresh store sidesteps that entirely.
        self.track_store, self._track_filter = self._create_track_store()
        self.track_view.set_model(self._track_filter)
        self._track_sort_col = None
        self._track_sort_order = Gtk.SortType.ASCENDING
        for c in self.track_view.get_columns():
            c.set_sort_indicator(False)

    def _sort_track_number(self, model, it1, it2, _data):
        def to_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        a, b = to_int(model[it1][1]), to_int(model[it2][1])
        return (a > b) - (a < b)

    def _sort_duration(self, model, it1, it2, _data):
        def to_seconds(v):
            try:
                m, s = v.split(":")
                return int(m) * 60 + int(s)
            except (ValueError, AttributeError):
                return 0

        a, b = to_seconds(model[it1][5]), to_seconds(model[it2][5])
        return (a > b) - (a < b)

    def _on_track_column_clicked(self, column, col_idx):
        if self._track_sort_col == col_idx:
            self._track_sort_order = (
                Gtk.SortType.DESCENDING
                if self._track_sort_order == Gtk.SortType.ASCENDING
                else Gtk.SortType.ASCENDING
            )
        else:
            self._track_sort_order = Gtk.SortType.ASCENDING
        self._track_sort_col = col_idx
        for c in self.track_view.get_columns():
            c.set_sort_indicator(False)
        column.set_sort_indicator(True)
        column.set_sort_order(self._track_sort_order)
        self.track_store.set_sort_column_id(col_idx, self._track_sort_order)

    def _fill_artist_store(self):
        self._browser_loading = True
        seen = set()
        self.artist_store.clear()
        self.artist_store.append(("", _("All artists")))
        for t in self.all_tracks:
            name = track_artist(t)
            if name and name not in seen:
                seen.add(name)
        for name in sorted(seen, key=str.lower):
            self.artist_store.append((name, name))
        self._fill_album_store(self.all_tracks)
        self._browser_loading = True
        sel = self.artist_view.get_selection()
        if sel:
            sel.select_path(Gtk.TreePath.new_first())
        self._browser_loading = False

    def _fill_album_store(self, tracks):
        self._browser_loading = True
        seen = {}
        self.album_store.clear()
        self.album_store.append(("", _("All albums")))
        for t in tracks:
            pid = t.get("ParentId", "")
            if pid and pid not in seen:
                seen[pid] = t.get("Album", "?")
        for pid, name in sorted(seen.items(), key=lambda x: x[1].lower()):
            self.album_store.append((pid, name))
        sel = self.album_view.get_selection()
        if sel:
            sel.select_path(Gtk.TreePath.new_first())
        self._browser_loading = False

    def _on_artist_selected(self, selection):
        if self._browser_loading:
            return
        model, it = selection.get_selected()
        if not it:
            return
        self._filter_artist = model[it][0]
        self._filter_album = ""
        self._track_filter.refilter()
        artist_tracks = (
            self.all_tracks
            if not self._filter_artist
            else [t for t in self.all_tracks if track_artist(t) == self._filter_artist]
        )
        self._fill_album_store(artist_tracks)

    def _on_album_selected(self, selection):
        if self._browser_loading:
            return
        model, it = selection.get_selected()
        if not it:
            return
        self._filter_album = model[it][0]
        self._track_filter.refilter()

    # ── Suche ──
    def _on_search(self, entry):
        self._filter_query = entry.get_text().lower()
        self._track_filter.refilter()

    # ── Wiedergabe ──
    def _on_track_activated(self, treeview, path, col):
        row = treeview.get_model()[path]
        track_id = row[0]
        if not self.client:
            return
        track = next(
            (t for t in getattr(self, "all_tracks", []) if t["Id"] == track_id), None
        )
        self.now_playing.play_track(track_id, f"{row[3]} - {row[2]}", track)

    def _get_play_selection(self):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            if self.client:
                return self.playlist.get_selected_track()
            return None
        row = model[paths[0]]
        if not self.client:
            return None
        track = next(
            (t for t in getattr(self, "all_tracks", []) if t["Id"] == row[0]), None
        )
        return row[0], f"{row[3]} - {row[2]}", track

    def _toggle_mini(self, _btn):
        self.hide()
        self.mini.show()

    def _restore_from_mini(self):
        self.show()
        self.present()

    # ── Playlist ──
    def _on_track_right_click(self, widget, event):
        if event.button != 3:
            return
        path_info = widget.get_path_at_pos(int(event.x), int(event.y))
        if not path_info:
            return
        path = path_info[0]
        selection = widget.get_selection()
        if not selection.path_is_selected(path):
            selection.unselect_all()
            selection.select_path(path)
        menu = Gtk.Menu()
        item_add = Gtk.MenuItem(label=_("Add to Playlist"))
        item_add.connect(
            "activate",
            lambda _i: self.playlist.add_tracks(self._get_library_selection()),
        )
        menu.append(item_add)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _get_library_selection(self):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        tracks = []
        for path in paths:
            track_id = model[path][0]
            track = next(
                (t for t in getattr(self, "all_tracks", []) if t["Id"] == track_id),
                None,
            )
            if track:
                tracks.append(track)
        return tracks

    def _on_album_right_click(self, widget, event):
        if event.button != 3:
            return
        path_info = widget.get_path_at_pos(int(event.x), int(event.y))
        if not path_info:
            return
        path = path_info[0]
        widget.get_selection().select_path(path)
        album_id = self.album_store[path][0]
        if not album_id:
            return
        menu = Gtk.Menu()
        item_add = Gtk.MenuItem(label=_("Add to Playlist"))
        item_add.connect("activate", self._add_album_to_playlist, album_id)
        menu.append(item_add)
        item_burn = Gtk.MenuItem(label=_("Burn Album"))
        item_burn.connect("activate", self._burn_album, album_id)
        menu.append(item_burn)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _add_album_to_playlist(self, _item, album_id):
        tracks = sorted(
            (
                t
                for t in getattr(self, "all_tracks", [])
                if t.get("ParentId") == album_id
            ),
            key=lambda t: t.get("IndexNumber") or 0,
        )
        self.playlist.add_tracks(tracks)

    def _burn_album(self, _item, album_id):
        tracks = sorted(
            (
                t
                for t in getattr(self, "all_tracks", [])
                if t.get("ParentId") == album_id
            ),
            key=lambda t: t.get("IndexNumber") or 0,
        )
        if not tracks:
            return
        album_name = tracks[0].get("Album", "?")
        artist_name = track_artist(tracks[0])
        self.playlist.replace_with(tracks, f"{artist_name} – {album_name}")
        self._start_burn(None)

    # ── Einstellungen ──
    def _open_settings(self, _btn):
        dlg = SettingsDialog(self, self.config)
        response = dlg.run()
        vals = dlg.get_values()
        lang_changed = vals.get("language") != self.config.get("language", "en")
        # Only fields that actually affect the server connection warrant a
        # reconnect - switching the theme, burn speed, etc. shouldn't
        # trigger one (and a non-empty password always means the user is
        # actively trying to (re-)authenticate right now).
        connection_changed = bool(vals.get("password")) or any(
            vals.get(key) != self.config.get(key)
            for key in ("server_url", "username", "api_key")
        )
        dlg.destroy()
        if response == Gtk.ResponseType.OK:
            self.config.update(vals)
            save_config({k: v for k, v in self.config.items() if k != "password"})
            self.theme.update()
            if lang_changed:
                info = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text=_("Language changed"),
                )
                info.format_secondary_text(
                    _(
                        "Please restart Jellyburn for the language change to take effect."
                    )
                )
                info.run()
                info.destroy()
            elif connection_changed:
                self._connect()

    # ── Brennen ──
    def _start_burn(self, _btn):
        playlist_tracks = self.playlist.playlist_tracks
        if not playlist_tracks:
            return
        total_s = self.playlist.total_seconds()
        mode = "audio"
        if total_s > CD_MAX_SECONDS:
            est_bytes = total_s * (MP3_BITRATE_KBPS * 1000 // 8)
            if est_bytes > CD_DATA_MAX_BYTES:
                show_error(
                    self,
                    _(
                        "Playlist is too long even for an MP3 data CD (~{mb} MB estimated, limit ~700 MB)."
                    ).format(mb=est_bytes // 1_000_000),
                )
                return

            if self.config.get("mp3_auto_switch"):
                mode = "mp3"
            else:
                dlg = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.NONE,
                    text=_("Playlist too long!"),
                )
                dlg.format_secondary_text(
                    _(
                        "The playlist is {duration} long – a CD holds only 74:00."
                    ).format(duration=seconds_to_mmss(total_s))
                )
                dlg.add_button(_("Burn as MP3 data CD"), Gtk.ResponseType.OK)
                dlg.add_button(_("Audio CD anyway"), Gtk.ResponseType.APPLY)
                dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
                dlg.set_default_response(Gtk.ResponseType.OK)
                resp = dlg.run()
                dlg.destroy()
                if resp == Gtk.ResponseType.OK:
                    mode = "mp3"
                elif resp == Gtk.ResponseType.APPLY:
                    mode = "audio"
                else:
                    return

        dlg = BurnDialog(self, playlist_tracks, self.client, self.config, mode=mode)
        dlg.run()
        dlg.destroy()
