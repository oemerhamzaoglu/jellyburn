import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

DARK_CSS = """
window, .main-box {
    background-color: #12121a;
    color: #d8d8e0;
}
headerbar, headerbar * {
    background-color: #1a1a2e;
    border-bottom: 1px solid #0a0a14;
    color: #d8d8e0;
}
headerbar button {
    background: transparent;
    border: none;
    color: #9090b0;
    padding: 4px 6px;
}
headerbar button:hover { color: #e94560; }
searchentry {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    border-radius: 4px;
    color: #d8d8e0;
    padding: 4px 8px;
}
searchentry:focus { border-color: #e94560; }
treeview {
    background-color: #12121a;
    color: #d8d8e0;
}
treeview:selected {
    background-color: #e94560;
    color: #ffffff;
}
treeview header button {
    background-color: #1a1a2e;
    color: #7070a0;
    border-bottom: 1px solid #0a0a14;
    font-size: 11px;
    letter-spacing: 0.05em;
    padding: 3px 6px;
}
separator { background-color: #222236; }
.lib-status {
    font-size: 11px;
    color: #6060a0;
    padding: 2px 6px;
}
.panel-right {
    background-color: #16162a;
    border-left: 1px solid #222236;
}
.panel-right treeview { background-color: #16162a; }
.cd-counter {
    font-family: monospace;
    font-size: 12px;
    color: #7070a0;
    padding: 0 8px;
}
.cd-counter.over-limit { color: #e94560; font-weight: bold; }
progressbar trough {
    background-color: #1e1e30;
    border-radius: 3px;
    min-height: 6px;
}
progressbar progress {
    background-image: none;
    background-color: #3dc47e;
    border-radius: 3px;
    min-height: 6px;
}
progressbar.cd-bar progress {
    background-image: none;
    background-color: #3dc47e;
}
progressbar.cd-yellow progress {
    background-image: none;
    background-color: #e8a838;
}
progressbar.cd-red progress {
    background-image: none;
    background-color: #e94560;
}
button {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    border-radius: 3px;
    color: #d8d8e0;
    padding: 4px 10px;
}
button:hover {
    background-color: #2a2a40;
    border-color: #e94560;
}
.add-btn {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    color: #9090b0;
    font-size: 12px;
}
.add-btn:hover { border-color: #e94560; color: #e94560; }
.burn-btn {
    background-color: #e94560;
    border: none;
    border-radius: 4px;
    color: #ffffff;
    font-weight: bold;
    font-size: 13px;
    padding: 8px 0;
    letter-spacing: 0.04em;
}
.burn-btn:hover { background-color: #c73652; }
.burn-btn:disabled { background-color: #2a2a40; color: #5050a0; }
.now-playing-box {
    background-color: #1a1a2e;
    border-top: 1px solid #222236;
    padding: 8px;
}
.now-playing-title {
    font-weight: bold;
    font-size: 13px;
    color: #d8d8e0;
}
.now-playing-sub {
    font-size: 11px;
    color: #7070a0;
}
scale.playback trough {
    background-color: #2a2a40;
    min-height: 4px;
    border-radius: 2px;
}
scale.playback highlight {
    background-color: #e94560;
    min-height: 4px;
    border-radius: 2px;
}
scale.playback slider {
    background-color: #e94560;
    border: none;
    border-radius: 50%;
    min-width: 12px;
    min-height: 12px;
}
scale.playback slider:hover {
    background-color: #ff6080;
}
.art-placeholder {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    border-radius: 3px;
    color: #3a3a60;
    font-size: 32px;
}
dialog { background-color: #1a1a2e; }
dialog .dialog-action-area button { font-size: 12px; }
.mini-player {
    background-color: #1a1a2e;
    border: 1px solid #222236;
}
paned separator {
    background-color: #222236;
    min-width: 1px;
    min-height: 1px;
}
notebook, notebook > stack {
    background-color: #16162a;
    border: none;
}
notebook > header {
    background-color: #1a1a2e;
    border: none;
    border-bottom: 1px solid #0a0a14;
    box-shadow: none;
}
notebook > header tabs tab {
    background-color: transparent;
    border: none;
    box-shadow: none;
    color: #7070a0;
    padding: 6px 14px;
}
notebook > header tabs tab:checked {
    color: #e94560;
    border-bottom: 2px solid #e94560;
}
.eq-window {
    background-color: #12121a;
    color: #d8d8e0;
}
.eq-window scale trough {
    background-color: #2a2a40;
    min-width: 4px;
    border-radius: 2px;
}
.eq-window scale highlight {
    background-color: #e94560;
    min-width: 4px;
    border-radius: 2px;
}
.eq-window scale slider {
    background-color: #e94560;
    border: none;
    border-radius: 50%;
    min-width: 14px;
    min-height: 14px;
}
.eq-window scale slider:hover {
    background-color: #ff6080;
}
"""


class ThemeManager:
    def __init__(self, screen, config):
        self._screen = screen
        self._config = config
        self._dark_css_provider = Gtk.CssProvider()
        self._dark_css_provider.load_from_data(DARK_CSS.encode())
        self._dark_css_active = False
        self.update()

    def update(self):
        # Jellyburn's custom CSS is a dark-only design (not
        # theme-adaptive) - "light" skips it entirely and lets the
        # default GTK theme render; "system" mirrors whatever GTK
        # currently reports as the preferred scheme (best-effort on
        # GTK3, since there is no reliable portal-based color-scheme
        # query without extra dependencies); "dark" always forces it.
        theme = self._config.get("theme", "dark")
        settings = Gtk.Settings.get_default()

        if theme == "light":
            want_dark = False
        elif theme == "dark":
            want_dark = True
        else:  # system
            # "gtk-application-prefer-dark-theme" is an app-side hint for
            # Adwaita's dark variant, not a reliable signal for whether
            # the actual active GTK theme (e.g. a custom dark theme like
            # mx-comfort-dark) is dark. Heuristic: check the theme name.
            theme_name = (settings.get_property("gtk-theme-name") or "").lower()
            want_dark = "dark" in theme_name

        if settings is not None and theme != "system":
            settings.set_property("gtk-application-prefer-dark-theme", want_dark)

        if want_dark and not self._dark_css_active:
            Gtk.StyleContext.add_provider_for_screen(
                self._screen,
                self._dark_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            self._dark_css_active = True
        elif not want_dark and self._dark_css_active:
            Gtk.StyleContext.remove_provider_for_screen(
                self._screen, self._dark_css_provider
            )
            self._dark_css_active = False
