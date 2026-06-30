#!/usr/bin/env python3
"""
Jellyburn – Jellyfin music player and CD burner.
"""

import os
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .config import check_dependencies, load_config
from .i18n import setup_i18n, _
from .ui.main_window import MainWindow


def _install_desktop_integration():
    """Installs .desktop file and icon to ~/.local on first run."""
    marker = os.path.expanduser("~/.local/share/applications/jellyburn.desktop")
    if os.path.exists(marker):
        return

    pkg_dir = os.path.dirname(__file__)

    # Icon
    icon_src = os.path.join(pkg_dir, "icons", "jellyburn.svg")
    icon_dst_dir = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")
    icon_dst = os.path.join(icon_dst_dir, "jellyburn.svg")
    os.makedirs(icon_dst_dir, exist_ok=True)
    if os.path.exists(icon_src) and not os.path.exists(icon_dst):
        import shutil
        shutil.copy2(icon_src, icon_dst)

    # .desktop file
    desktop_src = os.path.join(pkg_dir, "data", "jellyburn.desktop")
    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)
    if os.path.exists(desktop_src):
        import shutil
        shutil.copy2(desktop_src, marker)

    # Refresh caches (best-effort)
    os.system("update-desktop-database ~/.local/share/applications/ 2>/dev/null")
    os.system("gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null")


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
    _install_desktop_integration()
    app = JellyburnApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
