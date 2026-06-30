#!/usr/bin/env python3
"""
Jellyburn – Jellyfin music player and CD burner.
"""

import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .config import check_dependencies, load_config
from .i18n import setup_i18n, _
from .ui.main_window import MainWindow


class JellyburnApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="de.linumed.jellyfinburner")

    def do_activate(self):
        cfg = load_config()
        setup_i18n(cfg.get("language", "en"))

        win = MainWindow(application=self)
        win.show_all()
        missing = check_dependencies()
        if missing:
            dlg = Gtk.MessageDialog(
                transient_for=win, modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text=_("Missing system dependencies"),
            )
            dlg.format_secondary_text(
                _("The following programs were not found:") + "\n\n" +
                "\n".join(f"  • {label}" for label in missing) +
                "\n\n" + _("Please install them to enable all features.")
            )
            dlg.run()
            dlg.destroy()


def main():
    app = JellyburnApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
