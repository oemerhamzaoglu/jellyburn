import os
import resource
import subprocess
import tempfile
import threading


def resolve_sg_device(sr_device):
    """Löst /dev/srX in das passende /dev/sgX auf (für wodim nötig)."""
    try:
        name = os.path.basename(sr_device)  # z.B. "sr0"
        sg_dir = f"/sys/block/{name}/device/scsi_generic"
        sg_name = os.listdir(sg_dir)[0]     # z.B. "sg1"
        return f"/dev/{sg_name}"
    except Exception:
        return sr_device  # Fallback: original behalten

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from .api import track_artist
from .config import check_dependencies, get_burn_tool


class BurnDialog(Gtk.Dialog):
    def __init__(self, parent, playlist, client, config):
        super().__init__(title="CD brennen", transient_for=parent, modal=True)
        self.set_default_size(500, 400)
        self.playlist = playlist
        self.client = client
        self.config = config
        self.cancelled = False
        self._burning = False

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        box.pack_start(Gtk.Label(label="<b>Tracks auf CD:</b>", use_markup=True, xalign=0), False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(150)
        tv = Gtk.TextView(editable=False, monospace=True)
        buf = tv.get_buffer()
        lines = "\n".join(
            f"{i+1:2}. {track_artist(t) or '?'} - {t.get('Name','?')}"
            f" ({client.format_duration(t.get('RunTimeTicks', 0))})"
            for i, t in enumerate(playlist)
        )
        buf.set_text(lines)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)

        self.status_label = Gtk.Label(label="Bereit zum Brennen.", xalign=0)
        self.status_label.set_line_wrap(True)
        box.pack_start(self.status_label, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        box.pack_start(self.progress, False, False, 0)

        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        btn_box.set_margin_top(4)

        self.cancel_btn = Gtk.Button(label="Abbrechen")
        self.cancel_btn.connect("clicked", self._on_cancel)
        btn_box.pack_start(self.cancel_btn, False, False, 0)

        self.burn_btn = Gtk.Button(label="Jetzt brennen")
        self.burn_btn.get_style_context().add_class("suggested-action")
        self.burn_btn.connect("clicked", self._on_burn_clicked)
        btn_box.pack_start(self.burn_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 0)
        self.show_all()

    def _on_burn_clicked(self, _):
        missing = check_dependencies()
        if missing:
            self._set_status("Fehlende Programme: " + ", ".join(missing))
            return
        self.burn_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(False)
        self._burning = True
        threading.Thread(target=self._burn_thread, daemon=True).start()

    def _on_cancel(self, _):
        if self._burning:
            self.cancelled = True
        else:
            self.response(Gtk.ResponseType.CANCEL)

    def _on_burn_done(self):
        self.cancel_btn.set_label("Schließen")
        self.cancel_btn.set_sensitive(True)

    def _set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _set_progress(self, fraction, text=""):
        def _update():
            self.progress.set_fraction(fraction)
            if text:
                self.progress.set_text(text)
        GLib.idle_add(_update)

    def _burn_thread(self):
        tmpdir = tempfile.mkdtemp(prefix="jellyfin_burn_")
        wav_files = []

        try:
            total = len(self.playlist)
            for i, track in enumerate(self.playlist):
                if self.cancelled:
                    return
                name = track.get("Name", f"track_{i+1}")
                artist = track_artist(track)
                self._set_status(f"Lade: {artist} - {name} ({i+1}/{total})")
                self._set_progress(i / total / 2, f"Download {i+1}/{total}")

                url = self.client.get_download_url(track["Id"])
                resp = self.client.session.get(url, stream=True)
                resp.raise_for_status()

                src_path = os.path.join(tmpdir, f"track_{i+1:02d}_src")
                with open(src_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)

                wav_path = os.path.join(tmpdir, f"track_{i+1:02d}.wav")
                self._set_status(f"Konvertiere: {name}")
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", src_path,
                     "-ar", "44100", "-ac", "2", "-f", "wav", wav_path],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    self._set_status(
                        f"Konvertierung fehlgeschlagen: {name}\n{result.stderr.strip()[-400:]}"
                    )
                    return
                wav_files.append(wav_path)
                os.unlink(src_path)
                self._set_progress((i + 1) / total / 2, f"Konvertiert {i+1}/{total}")

            if self.cancelled:
                return

            self._set_status("Starte Brennvorgang – bitte nicht abbrechen...")
            self._set_progress(0.5, "Brennen...")

            device = resolve_sg_device(self.config.get("cd_device", "/dev/sr0"))
            speed = self.config.get("burn_speed", 4)
            burn_tool = get_burn_tool()
            if not burn_tool:
                self._set_status("Kein Brennprogramm gefunden.\nBitte installieren: sudo apt install cdrskin")
                return
            cmd = [burn_tool, f"dev={device}", f"speed={speed}", "-v", "-dao", "-audio", "-pad"] + wav_files

            def _raise_memlock():
                try:
                    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
                    if hard == resource.RLIM_INFINITY:
                        resource.setrlimit(resource.RLIMIT_MEMLOCK,
                                           (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
                    elif hard > soft:
                        resource.setrlimit(resource.RLIMIT_MEMLOCK, (hard, hard))
                except Exception:
                    pass

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, preexec_fn=_raise_memlock)
            output_lines = []
            for line in proc.stdout:
                line = line.strip()
                output_lines.append(line)
                if "%" in line or "Track" in line or "Writing" in line:
                    self._set_status(line)

            proc.wait()
            if proc.returncode == 0:
                self._set_status("CD erfolgreich gebrannt!")
                self._set_progress(1.0, "Fertig!")
            else:
                full = "\n".join(output_lines[-20:])
                if "RLIMIT_MEMLOCK" in full or "mmap" in full:
                    hint = (
                        f"Brenner-Fehler (Code {proc.returncode}) – Speicher-Lock-Problem.\n\n"
                        "Lösung: cdrskin installieren (empfohlen):\n"
                        "  sudo apt install cdrskin\n\n"
                        "Oder Rechte für wodim setzen:\n"
                        "  sudo setcap cap_ipc_lock+ep $(which wodim)\n\n"
                        f"Ausgabe:\n{full}"
                    )
                    self._set_status(hint)
                else:
                    self._set_status(f"Brenner-Fehler (Code {proc.returncode}):\n{full}")

        except Exception as e:
            self._set_status(f"Fehler: {e}")
        finally:
            for f in wav_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass
            GLib.idle_add(self._on_burn_done)
