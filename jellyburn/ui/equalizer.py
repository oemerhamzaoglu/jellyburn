import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from ..i18n import _
from ..player import EQ_FREQS

PRESETS = {
    "flat":    ("Flat",         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    "bass":    ("Bass Boost",   [8, 6, 4, 2, 0, 0, 0, 0, 0, 0]),
    "treble":  ("Treble Boost", [0, 0, 0, 0, 0, 0, 2, 4, 6, 8]),
    "vocal":   ("Vocal",        [-2, -2, 0, 2, 4, 4, 2, 0, -1, -2]),
    "rock":    ("Rock",         [5, 3, 0, -2, -3, 0, 2, 3, 4, 5]),
}


def _freq_label(freq):
    return f"{freq // 1000}k" if freq >= 1000 else str(freq)


class EqualizerWindow(Gtk.Window):
    def __init__(self, parent, bands, enabled, on_change):
        super().__init__(title=_("Equalizer"))
        self._on_change = on_change
        self._debounce_id = None
        self._updating = False

        self.set_default_size(420, 260)
        self.set_resizable(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.connect("delete-event", self._on_delete)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
        outer.get_style_context().add_class("eq-window")
        self.add(outer)

        top = Gtk.Box(spacing=8)
        self.chk_enabled = Gtk.CheckButton(label=_("Enable equalizer"))
        self.chk_enabled.set_active(enabled)
        self.chk_enabled.connect("toggled", self._on_value_changed)
        top.pack_start(self.chk_enabled, False, False, 0)

        top.pack_start(Gtk.Label(label=_("Preset:")), False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        for key, (label, _vals) in PRESETS.items():
            self.preset_combo.append(key, _(label))
        self.preset_combo.connect("changed", self._on_preset_selected)
        top.pack_start(self.preset_combo, True, True, 0)

        btn_reset = Gtk.Button(label=_("Reset"))
        btn_reset.connect("clicked", self._on_reset)
        top.pack_start(btn_reset, False, False, 0)

        outer.pack_start(top, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 0)

        sliders_box = Gtk.Box(spacing=6, homogeneous=True)
        self.sliders = []
        for freq, gain in zip(EQ_FREQS, bands):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scale = Gtk.Scale.new(Gtk.Orientation.VERTICAL, None)
            scale.set_range(-12, 12)
            scale.set_value(gain)
            scale.set_inverted(True)
            scale.set_draw_value(False)
            scale.set_size_request(-1, 140)
            scale.set_digits(0)
            scale.connect("value-changed", self._on_value_changed)
            self.sliders.append(scale)
            col.pack_start(scale, True, True, 0)
            col.pack_start(Gtk.Label(label=_freq_label(freq)), False, False, 0)
            sliders_box.pack_start(col, True, True, 0)

        outer.pack_start(sliders_box, True, True, 0)

        self.show_all()
        self.hide()

    def _on_delete(self, *_args):
        self.hide()
        return True

    def _on_preset_selected(self, combo):
        key = combo.get_active_id()
        if not key or key not in PRESETS:
            return
        _label, values = PRESETS[key]
        self._updating = True
        for scale, value in zip(self.sliders, values):
            scale.set_value(value)
        self._updating = False
        self._on_value_changed(None)

    def _on_reset(self, _btn):
        self.preset_combo.set_active_id("flat")

    def _on_value_changed(self, _widget):
        if self._updating:
            return
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(150, self._fire_change)

    def _fire_change(self):
        self._debounce_id = None
        bands = [s.get_value() for s in self.sliders]
        self._on_change(bands, self.chk_enabled.get_active())
        return False

    def present_window(self):
        self.show()
        self.present()
