import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango
import requests

from ..api import JellyfinClient, track_artist
from ..config import load_library_cache, save_config, save_library_cache
from ..i18n import _


class LibraryPane(Gtk.Box):
    """Server connection, artist/album browser, and track list."""

    def __init__(self, config, on_play_track, on_add_tracks, on_burn_album):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config = config
        self._on_play_track = on_play_track
        self._on_add_tracks = on_add_tracks
        self._on_burn_album = on_burn_album

        self.client = None
        self.all_tracks = []
        self._track_sort_col = None
        self._track_sort_order = Gtk.SortType.ASCENDING
        self._connecting = False
        self._connect_generation = 0
        self._filter_artist = ""
        self._filter_album = ""
        self._filter_query = ""
        self._browser_loading = False

        search_box = Gtk.Box(spacing=6, margin=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Search…"))
        self.search_entry.connect("search-changed", self._on_search)
        search_box.pack_start(self.search_entry, True, True, 0)
        self.pack_start(search_box, False, False, 0)
        self.pack_start(Gtk.Separator(), False, False, 0)

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

        self.pack_start(vpaned, True, True, 0)

        self.load_bar = Gtk.ProgressBar()
        self.load_bar.set_no_show_all(True)
        self.pack_start(self.load_bar, False, False, 0)

        self.lib_status = Gtk.Label(label=_("Not connected"), xalign=0, margin=4)
        self.lib_status.get_style_context().add_class("lib-status")
        self.pack_start(self.lib_status, False, False, 0)

    # ── Public API ──
    def get_selected_track(self):
        if not self.client:
            return None
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            return None
        row = model[paths[0]]
        track = next((t for t in self.all_tracks if t["Id"] == row[0]), None)
        return row[0], f"{row[3]} - {row[2]}", track

    def get_selected_tracks(self):
        sel = self.track_view.get_selection()
        model, paths = sel.get_selected_rows()
        tracks = []
        for path in paths:
            track_id = model[path][0]
            track = next((t for t in self.all_tracks if t["Id"] == track_id), None)
            if track:
                tracks.append(track)
        return tracks

    def connect_to_server(self):
        if not self.config.get("server_url"):
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

    # ── Verbindung ──
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
        track = next((t for t in self.all_tracks if t["Id"] == track_id), None)
        self._on_play_track(track_id, f"{row[3]} - {row[2]}", track)

    # ── Playlist-Aktionen (Rechtsklick) ──
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
            "activate", lambda _i: self._on_add_tracks(self.get_selected_tracks())
        )
        menu.append(item_add)
        menu.show_all()
        menu.popup_at_pointer(event)

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

    def _album_tracks(self, album_id):
        return sorted(
            (t for t in self.all_tracks if t.get("ParentId") == album_id),
            key=lambda t: t.get("IndexNumber") or 0,
        )

    def _add_album_to_playlist(self, _item, album_id):
        self._on_add_tracks(self._album_tracks(album_id))

    def _burn_album(self, _item, album_id):
        tracks = self._album_tracks(album_id)
        if not tracks:
            return
        album_name = tracks[0].get("Album", "?")
        artist_name = track_artist(tracks[0])
        self._on_burn_album(tracks, f"{artist_name} – {album_name}")
