import gettext
import os

_t = None


def setup_i18n(lang="en"):
    global _t
    locale_dir = os.path.join(os.path.dirname(__file__), "locales")
    if lang == "en":
        _t = lambda s: s
        return
    try:
        t = gettext.translation("jellyburn", localedir=locale_dir, languages=[lang])
        _t = t.gettext
    except FileNotFoundError:
        _t = lambda s: s


def _(text):
    if _t is None:
        return text
    return _t(text)
