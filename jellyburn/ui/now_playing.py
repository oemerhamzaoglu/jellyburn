import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Pango
import requests

from ..config import save_config
from ..i18n import _
from .equalizer import EqualizerWindow


class NowPlayingBox(Gtk.Box):
    """Now-playing display + playback controls (play/pause/stop/EQ/scrub)."""

    def __init__(self, player, config, get_client, get_selection):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin=8)
        self.player = player
        self.config = config
        self._get_client = get_client
        self._get_selection = get_selection
        self.eq_window = None
        self.mini = None
        self._scrubbing = False

        self.get_style_context().add_class("now-playing-box")

        self.art_image = Gtk.Image()
        self.art_image.set_size_request(56, 56)
        self.art_image.get_style_context().add_class("art-placeholder")
        self.pack_start(self.art_image, False, False, 0)

        np_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        np_info.set_valign(Gtk.Align.CENTER)

        self.np_title = Gtk.Label(label="", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.np_title.get_style_context().add_class("now-playing-title")

        self.np_sub = Gtk.Label(label="", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.np_sub.get_style_context().add_class("now-playing-sub")

        np_ctrl = Gtk.Box(spacing=4)
        self.btn_play = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic", Gtk.IconSize.BUTTON
        )
        self.btn_play.connect("clicked", self.toggle_play_pause)
        self.btn_stop = Gtk.Button.new_from_icon_name(
            "media-playback-stop-symbolic", Gtk.IconSize.BUTTON
        )
        self.btn_stop.connect("clicked", self.stop)
        self.btn_eq = Gtk.Button(label="EQ")
        self.btn_eq.set_tooltip_text(_("Equalizer"))
        self.btn_eq.connect("clicked", self._toggle_eq)
        self.np_time = Gtk.Label(label="", xalign=0)
        self.np_time.get_style_context().add_class("now-playing-sub")
        np_ctrl.pack_start(self.btn_play, False, False, 0)
        np_ctrl.pack_start(self.btn_stop, False, False, 0)
        np_ctrl.pack_start(self.btn_eq, False, False, 0)
        np_ctrl.pack_start(self.np_time, False, False, 4)

        self.np_progress = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, None)
        self.np_progress.set_draw_value(False)
        self.np_progress.set_range(0, 1)
        self.np_progress.set_value(0)
        self.np_progress.get_style_context().add_class("playback")
        self.np_progress.connect("button-press-event", self._on_scrub_start)
        self.np_progress.connect("button-release-event", self._on_scrub_end)

        np_info.pack_start(self.np_title, False, False, 0)
        np_info.pack_start(self.np_sub, False, False, 0)
        np_info.pack_start(np_ctrl, False, False, 0)
        np_info.pack_start(self.np_progress, False, False, 0)
        self.pack_start(np_info, True, True, 0)

    def set_mini(self, mini):
        self.mini = mini

    # ── Wiedergabe ──
    def play_selected(self):
        sel = self._get_selection()
        if not sel:
            return
        track_id, label, track = sel
        self.play_track(track_id, label, track)

    def toggle_play_pause(self, _btn=None):
        if self.player.is_playing:
            self.player.toggle_pause()
            self._set_play_icon(paused=self.player.is_paused)
        else:
            self.play_selected()

    def _set_play_icon(self, paused):
        icon = (
            "media-playback-start-symbolic"
            if paused
            else "media-playback-pause-symbolic"
        )
        self.btn_play.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))

    def play_track(self, track_id, label, track):
        client = self._get_client()

        # get_stream_url() calls get_user_id(), which does a blocking
        # network request the first time (or after auth fails) - never
        # call it directly from a signal handler, or a slow/unreachable
        # server freezes the whole UI for the request's timeout duration.
        def worker():
            try:
                url = client.get_stream_url(track_id)
            except requests.exceptions.RequestException as e:
                GLib.idle_add(
                    self.np_title.set_text, _("Playback error: {error}").format(error=e)
                )
                return
            GLib.idle_add(self._play_url, url, label, track)

        threading.Thread(target=worker, daemon=True).start()

    def _play_url(self, url, label, track=None):
        client = self._get_client()
        parts = label.split(" - ", 1)
        artist = parts[0] if len(parts) == 2 else ""
        title = parts[1] if len(parts) == 2 else label
        self.np_title.set_text(title)
        self.np_sub.set_text(artist)
        self.np_time.set_text("")
        self.np_progress.set_value(0)
        if self.mini:
            self.mini.set_track(title, artist)
        self._set_play_icon(paused=False)

        if track and client:
            threading.Thread(
                target=self._load_art, args=(track["Id"],), daemon=True
            ).start()
        else:
            GLib.idle_add(self.art_image.clear)

        def on_progress(fraction, time_str, elapsed, total):
            GLib.idle_add(self.np_time.set_text, time_str)
            if not self._scrubbing:
                GLib.idle_add(self.np_progress.set_range, 0, max(total, 1))
                GLib.idle_add(self.np_progress.set_value, elapsed)
            if self.mini:
                GLib.idle_add(self.mini.set_progress, elapsed, total, time_str)

        def on_error(msg):
            GLib.idle_add(self.np_title.set_text, msg)

        def on_finished():
            GLib.idle_add(self._set_play_icon, True)

        self.player.play(
            url,
            track,
            ticks_to_seconds=(client.ticks_to_seconds if client else (lambda x: 0)),
            on_progress=on_progress,
            on_error=on_error,
            on_finished=on_finished,
        )

    def _toggle_eq(self, _btn):
        if self.eq_window is None:
            self.eq_window = EqualizerWindow(
                self.get_toplevel(),
                self.config.get("eq_bands", [0.0] * 10),
                self.config.get("eq_enabled", False),
                self._on_eq_change,
            )
        self.eq_window.present_window()

    def _on_eq_change(self, bands, enabled):
        self.config["eq_bands"] = bands
        self.config["eq_enabled"] = enabled
        save_config({k: v for k, v in self.config.items() if k != "password"})
        self.player.set_eq(bands, enabled)

    def _on_scrub_start(self, widget, event):
        self._scrubbing = True

    def _on_scrub_end(self, widget, event):
        self._scrubbing = False
        if self.player.is_playing:
            self.player.seek(widget.get_value())

    def _load_art(self, item_id):
        client = self._get_client()
        try:
            url = (
                f"{client.server_url}/Items/{item_id}/Images/Primary"
                f"?fillHeight=56&fillWidth=56&quality=80&api_key={client.api_key}"
            )
            resp = client.session.get(url, timeout=8)
            if resp.status_code == 200:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(resp.content)
                loader.close()
                pixbuf = loader.get_pixbuf()
                GLib.idle_add(self.art_image.set_from_pixbuf, pixbuf)
                if self.mini:
                    GLib.idle_add(self.mini.set_art, pixbuf)
                return
        except Exception:
            pass
        GLib.idle_add(self.art_image.clear)
        if self.mini:
            GLib.idle_add(self.mini.set_art, None)

    def stop(self, _btn=None):
        self.player.stop()
        self.np_title.set_text("")
        self.np_sub.set_text("")
        self.np_time.set_text("")
        self.np_progress.set_value(0)
        self.art_image.clear()
        if self.mini:
            self.mini.clear()
        self._set_play_icon(paused=True)
