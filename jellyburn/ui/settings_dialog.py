import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..config import detect_cd_devices


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Einstellungen", transient_for=parent, modal=True)
        self.set_default_size(440, 320)
        self.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Speichern", Gtk.ResponseType.OK)

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

        # CD-Laufwerk: ComboBox mit erkannten Geräten + manuelle Eingabe
        self._devices = detect_cd_devices()
        self.e_device = Gtk.ComboBoxText.new_with_entry()
        current = config.get("cd_device", "/dev/sr0")
        for dev, label in self._devices:
            self.e_device.append(dev, label)
        if self._devices:
            # Gespeichertes Gerät vorauswählen
            self.e_device.set_active_id(current)
            if self.e_device.get_active_id() is None:
                # Gespeichertes Gerät nicht in Liste → manuell eintragen
                self.e_device.get_child().set_text(current)
        else:
            self.e_device.get_child().set_text(current)

        if not self._devices:
            self.e_device.set_tooltip_text("Kein optisches Laufwerk erkannt – Pfad manuell eingeben")

        row("CD-Laufwerk:", self.e_device, 4)

        self.e_speed = Gtk.SpinButton.new_with_range(1, 52, 1)
        self.e_speed.set_value(config.get("burn_speed", 4))
        row("Brenngeschwindigkeit:", self.e_speed, 5)

        self.show_all()

    def get_values(self):
        # active_id ist der dev-Pfad; sonst den eingetippten Text nehmen
        device = self.e_device.get_active_id() or self.e_device.get_child().get_text().strip()
        return {
            "server_url": self.e_url.get_text().strip(),
            "username": self.e_user.get_text().strip(),
            "password": self.e_pass.get_text(),
            "api_key": self.e_apikey.get_text().strip(),
            "cd_device": device,
            "burn_speed": int(self.e_speed.get_value()),
        }
