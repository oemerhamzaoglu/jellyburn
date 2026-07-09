import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..i18n import _


def show_error(parent, msg):
    dlg = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text=msg,
    )
    dlg.run()
    dlg.destroy()


def prompt_text(parent, title, default=""):
    dlg = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("OK"), Gtk.ResponseType.OK)
    entry = Gtk.Entry(text=default)
    entry.set_activates_default(True)
    dlg.set_default_response(Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.pack_start(entry, True, True, 0)
    dlg.show_all()
    result = None
    if dlg.run() == Gtk.ResponseType.OK:
        text = entry.get_text().strip()
        if text:
            result = text
    dlg.destroy()
    return result
