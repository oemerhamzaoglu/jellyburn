#!/usr/bin/env python3
"""
Jellyburn – Jellyfin music player and CD burner.
"""

import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .config import check_dependencies
from .ui.main_window import MainWindow


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


def main():
    app = JellyburnApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
