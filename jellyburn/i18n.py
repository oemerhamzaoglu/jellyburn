import gettext
import os

_t = None


def _identity(s):
    return s


def setup_i18n(lang="en"):
    global _t
    locale_dir = os.path.join(os.path.dirname(__file__), "locales")
    if lang == "en":
        _t = _identity
        return
    try:
        t = gettext.translation("jellyburn", localedir=locale_dir, languages=[lang])
        _t = t.gettext
    except FileNotFoundError:
        _t = _identity


def _(text):
    if _t is None:
        return text
    return _t(text)
