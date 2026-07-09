import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..config import detect_cd_devices
from ..i18n import _

LANGUAGES = [
    ("en", "English"),
    ("de", "Deutsch"),
]


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title=_("Settings"), transient_for=parent, modal=True)
        self.set_default_size(440, 360)
        self.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                         _("Save"), Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, margin=16)
        self.get_content_area().pack_start(grid, True, True, 0)

        def row(label, widget, i):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
            widget.set_hexpand(True)

        self.e_url = Gtk.Entry(text=config.get("server_url", ""))
        self.e_url.set_placeholder_text("https://jellyfin.example.com")
        row(_("Server URL:"), self.e_url, 0)

        self.e_user = Gtk.Entry(text=config.get("username", ""))
        self.e_user.set_placeholder_text(_("Optional if API key is set"))
        row(_("Username:"), self.e_user, 1)

        self.e_pass = Gtk.Entry(text="")
        self.e_pass.set_visibility(False)
        self.e_pass.set_placeholder_text(_("Password (used once for login)"))
        row(_("Password:"), self.e_pass, 2)

        self.e_apikey = Gtk.Entry(text=config.get("api_key", ""))
        self.e_apikey.set_placeholder_text(_("API key from Jellyfin dashboard"))
        row(_("API Key:"), self.e_apikey, 3)

        self._devices = detect_cd_devices()
        self.e_device = Gtk.ComboBoxText.new_with_entry()
        current = config.get("cd_device", "/dev/sr0")
        for dev, label in self._devices:
            self.e_device.append(dev, label)
        if self._devices:
            self.e_device.set_active_id(current)
            if self.e_device.get_active_id() is None:
                self.e_device.get_child().set_text(current)
        else:
            self.e_device.get_child().set_text(current)
        if not self._devices:
            self.e_device.set_tooltip_text(_("No optical drive detected – enter path manually"))
        row(_("CD Drive:"), self.e_device, 4)

        self.e_speed = Gtk.SpinButton.new_with_range(1, 52, 1)
        self.e_speed.set_value(config.get("burn_speed", 4))
        row(_("Burn Speed:"), self.e_speed, 5)

        self.e_lang = Gtk.ComboBoxText()
        current_lang = config.get("language", "en")
        for code, name in LANGUAGES:
            self.e_lang.append(code, name)
        self.e_lang.set_active_id(current_lang)
        row(_("Language:"), self.e_lang, 6)

        self.e_cdtext = Gtk.CheckButton(label=_("Write CD-Text (album/track info on disc)"))
        self.e_cdtext.set_active(config.get("cd_text", True))
        grid.attach(self.e_cdtext, 1, 7, 1, 1)

        self.e_mp3_switch = Gtk.CheckButton(
            label=_("Auto-switch to MP3 data CD if playlist is too long"))
        self.e_mp3_switch.set_active(config.get("mp3_auto_switch", False))
        grid.attach(self.e_mp3_switch, 1, 8, 1, 1)

        self.show_all()

    def get_values(self):
        device = self.e_device.get_active_id() or self.e_device.get_child().get_text().strip()
        return {
            "server_url": self.e_url.get_text().strip(),
            "username": self.e_user.get_text().strip(),
            "password": self.e_pass.get_text(),
            "api_key": self.e_apikey.get_text().strip(),
            "cd_device": device,
            "burn_speed": int(self.e_speed.get_value()),
            "language": self.e_lang.get_active_id() or "en",
            "cd_text": self.e_cdtext.get_active(),
            "mp3_auto_switch": self.e_mp3_switch.get_active(),
        }
