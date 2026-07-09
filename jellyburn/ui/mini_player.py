import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango


class MiniPlayer(Gtk.Window):
    def __init__(self, player, on_play, on_stop, on_restore):
        super().__init__(title="Jellyburn")
        self.player = player
        self._on_play = on_play
        self._on_stop = on_stop
        self._on_restore = on_restore
        self._scrubbing = False

        self.set_default_size(320, 88)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        # X-Button → zurück zum Hauptfenster statt schließen
        self.connect("delete-event", self._restore)

        self._build_ui()
        # Startet versteckt – wird erst per Toggle eingeblendet

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.get_style_context().add_class("mini-player")
        self.add(outer)

        handle = Gtk.EventBox()
        handle.connect("button-press-event", self._on_drag)

        row = Gtk.Box(spacing=8, margin=8)
        handle.add(row)

        self.art = Gtk.Image()
        self.art.set_size_request(56, 56)
        self.art.get_style_context().add_class("art-placeholder")
        row.pack_start(self.art, False, False, 0)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_valign(Gtk.Align.CENTER)

        self.lbl_title = Gtk.Label(
            label="", xalign=0, ellipsize=Pango.EllipsizeMode.END
        )
        self.lbl_title.get_style_context().add_class("now-playing-title")

        self.lbl_sub = Gtk.Label(label="", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.lbl_sub.get_style_context().add_class("now-playing-sub")

        ctrl = Gtk.Box(spacing=4)
        btn_play = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic", Gtk.IconSize.BUTTON
        )
        btn_play.connect("clicked", lambda _: self._on_play())
        btn_stop = Gtk.Button.new_from_icon_name(
            "media-playback-stop-symbolic", Gtk.IconSize.BUTTON
        )
        btn_stop.connect("clicked", lambda _: self._on_stop())
        self.lbl_time = Gtk.Label(label="", xalign=0)
        self.lbl_time.get_style_context().add_class("now-playing-sub")
        ctrl.pack_start(btn_play, False, False, 0)
        ctrl.pack_start(btn_stop, False, False, 0)
        ctrl.pack_start(self.lbl_time, False, False, 4)

        # Expand-Button – zurück zum Hauptfenster
        btn_expand = Gtk.Button.new_from_icon_name(
            "view-fullscreen-symbolic", Gtk.IconSize.BUTTON
        )
        btn_expand.set_tooltip_text("Vollansicht")
        btn_expand.connect("clicked", self._restore)
        ctrl.pack_end(btn_expand, False, False, 0)

        info.pack_start(self.lbl_title, False, False, 0)
        info.pack_start(self.lbl_sub, False, False, 0)
        info.pack_start(ctrl, False, False, 0)
        row.pack_start(info, True, True, 0)

        outer.pack_start(handle, True, True, 0)

        self.scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, None)
        self.scale.set_draw_value(False)
        self.scale.set_range(0, 1)
        self.scale.set_margin_start(8)
        self.scale.set_margin_end(8)
        self.scale.set_margin_bottom(6)
        self.scale.get_style_context().add_class("playback")
        self.scale.connect(
            "button-press-event", lambda *_: setattr(self, "_scrubbing", True)
        )
        self.scale.connect("button-release-event", self._on_scrub_end)
        outer.pack_start(self.scale, False, False, 0)

        self.show_all()
        self.hide()

    def _restore(self, *_):
        self.hide()
        self._on_restore()
        return True  # delete-event: True verhindert das Schließen

    def _on_drag(self, widget, event):
        if event.button == 1:
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)

    def _on_scrub_end(self, widget, event):
        self._scrubbing = False
        if self.player.is_playing:
            self.player.seek(widget.get_value())

    # ── Public update API ──────────────────────────────────────────────────────

    def set_track(self, title, artist):
        self.lbl_title.set_text(title)
        self.lbl_sub.set_text(artist)

    def set_art(self, pixbuf):
        if pixbuf:
            self.art.set_from_pixbuf(pixbuf)
        else:
            self.art.clear()

    def set_progress(self, elapsed, total, time_str):
        self.lbl_time.set_text(time_str)
        if not self._scrubbing:
            self.scale.set_range(0, max(total, 1))
            self.scale.set_value(elapsed)

    def clear(self):
        self.lbl_title.set_text("")
        self.lbl_sub.set_text("")
        self.lbl_time.set_text("")
        self.scale.set_value(0)
        self.art.clear()
