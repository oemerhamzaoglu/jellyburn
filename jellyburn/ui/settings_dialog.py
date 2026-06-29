import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Einstellungen", transient_for=parent, modal=True)
        self.set_default_size(420, 300)
        self.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Speichern", Gtk.ResponseType.OK)
        self.config = config

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, margin=16)
        self.get_content_area().pack_start(grid, True, True, 0)

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
