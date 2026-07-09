import os
import resource
import shutil
import subprocess
import tempfile
import threading


def _cue_escape(text):
    return (text or "").replace('"', "'")


def build_cue_sheet(playlist, wav_names, track_artist):
    album = playlist[0].get("Album", "") if playlist else ""
    album_artist = track_artist(playlist[0]) if playlist else ""
    lines = [
        f'PERFORMER "{_cue_escape(album_artist)}"',
        f'TITLE "{_cue_escape(album)}"',
    ]
    for i, (track, wav_name) in enumerate(zip(playlist, wav_names)):
        lines.append(f'FILE "{wav_name}" WAVE')
        lines.append(f"  TRACK {i+1:02d} AUDIO")
        lines.append(f'    TITLE "{_cue_escape(track.get("Name", ""))}"')
        lines.append(f'    PERFORMER "{_cue_escape(track_artist(track))}"')
        lines.append("    INDEX 01 00:00:00")
    return "\n".join(lines) + "\n"


def resolve_sg_device(sr_device):
    """Löst /dev/srX in das passende /dev/sgX auf (für wodim nötig)."""
    try:
        name = os.path.basename(sr_device)  # z.B. "sr0"
        sg_dir = f"/sys/block/{name}/device/scsi_generic"
        sg_name = os.listdir(sg_dir)[0]  # z.B. "sg1"
        return f"/dev/{sg_name}"
    except Exception:
        return sr_device  # Fallback: original behalten


import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from .api import track_artist
from .config import (
    CD_DATA_MAX_BYTES,
    MP3_BITRATE_KBPS,
    check_dependencies,
    get_burn_tool,
    get_iso_tool,
)
from .i18n import _
from .playlists import sanitize_name


class BurnDialog(Gtk.Dialog):
    def __init__(self, parent, playlist, client, config, mode="audio"):
        super().__init__(title=_("Burn CD"), transient_for=parent, modal=True)
        self.set_default_size(500, 400)
        self.playlist = playlist
        self.client = client
        self.config = config
        self.mode = mode
        self.cancelled = False
        self._burning = False

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        mode_text = (
            _("Burning as: MP3 data CD ({kbps} kbps)").format(kbps=MP3_BITRATE_KBPS)
            if mode == "mp3"
            else _("Burning as: Audio CD")
        )
        box.pack_start(
            Gtk.Label(label=f"<b>{mode_text}</b>", use_markup=True, xalign=0),
            False,
            False,
            0,
        )

        box.pack_start(
            Gtk.Label(label=f"<b>{_('Tracks on CD:')}</b>", use_markup=True, xalign=0),
            False,
            False,
            0,
        )

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

        self.status_label = Gtk.Label(label=_("Ready to burn."), xalign=0)
        self.status_label.set_line_wrap(True)
        box.pack_start(self.status_label, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        box.pack_start(self.progress, False, False, 0)

        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        btn_box.set_margin_top(4)

        self.cancel_btn = Gtk.Button(label=_("Cancel"))
        self.cancel_btn.connect("clicked", self._on_cancel)
        btn_box.pack_start(self.cancel_btn, False, False, 0)

        self.burn_btn = Gtk.Button(label=_("Burn now"))
        self.burn_btn.get_style_context().add_class("suggested-action")
        self.burn_btn.connect("clicked", self._on_burn_clicked)
        btn_box.pack_start(self.burn_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 0)
        self.show_all()

    def _on_burn_clicked(self, _btn):
        missing = check_dependencies()
        if missing:
            self._set_status(_("Missing programs: ") + ", ".join(missing))
            return
        if self.mode == "mp3" and not get_iso_tool():
            self._set_status(
                _(
                    "No ISO creation tool found.\nPlease install: sudo apt install xorriso"
                )
            )
            return
        self.burn_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(False)
        self._burning = True
        threading.Thread(target=self._burn_thread, daemon=True).start()

    def _on_cancel(self, _btn):
        if self._burning:
            self.cancelled = True
        else:
            self.response(Gtk.ResponseType.CANCEL)

    def _on_burn_done(self):
        self._burning = False
        self.cancel_btn.set_label(_("Close"))
        self.cancel_btn.set_sensitive(True)

    def _set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _set_progress(self, fraction, text=""):
        def _update():
            self.progress.set_fraction(fraction)
            if text:
                self.progress.set_text(text)

        GLib.idle_add(_update)

    def _raise_memlock(self):
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
            if hard == resource.RLIM_INFINITY:
                resource.setrlimit(
                    resource.RLIMIT_MEMLOCK,
                    (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
                )
            elif hard > soft:
                resource.setrlimit(resource.RLIMIT_MEMLOCK, (hard, hard))
        except Exception:
            pass

    def _run_burn_process(self, cmd):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=self._raise_memlock,
        )
        output_lines = []
        for line in proc.stdout:
            line = line.strip()
            output_lines.append(line)
            if "%" in line or "Track" in line or "Writing" in line:
                self._set_status(line)
        proc.wait()
        return proc.returncode, output_lines

    def _handle_burn_result(self, returncode, output_lines):
        if returncode == 0:
            self._set_status(_("CD burned successfully!"))
            self._set_progress(1.0, _("Done!"))
        else:
            full = "\n".join(output_lines[-20:])
            if "RLIMIT_MEMLOCK" in full or "mmap" in full:
                hint = _(
                    "Burn error (code {code}) – memory lock problem.\n\n"
                    "Fix: install cdrskin (recommended):\n"
                    "  sudo apt install cdrskin\n\n"
                    "Or set permissions for wodim:\n"
                    "  sudo setcap cap_ipc_lock+ep $(which wodim)\n\n"
                    "Output:\n{output}"
                ).format(code=returncode, output=full)
                self._set_status(hint)
            else:
                self._set_status(
                    _("Burn error (code {code}):\n{output}").format(
                        code=returncode, output=full
                    )
                )

    def _burn_thread(self):
        tmpdir = tempfile.mkdtemp(prefix="jellyfin_burn_")
        try:
            if self.mode == "mp3":
                self._burn_mp3(tmpdir)
            else:
                self._burn_audio(tmpdir)
        except Exception as e:
            self._set_status(_("Error: {error}").format(error=e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            GLib.idle_add(self._on_burn_done)

    def _burn_audio(self, tmpdir):
        wav_files = []
        total = len(self.playlist)
        for i, track in enumerate(self.playlist):
            if self.cancelled:
                return
            name = track.get("Name", f"track_{i+1}")
            artist = track_artist(track)
            self._set_status(
                _("Downloading: {artist} - {name} ({i}/{total})").format(
                    artist=artist, name=name, i=i + 1, total=total
                )
            )
            self._set_progress(
                i / total / 2, _("Download {i}/{total}").format(i=i + 1, total=total)
            )

            url = self.client.get_download_url(track["Id"])
            resp = self.client.session.get(url, stream=True)
            resp.raise_for_status()

            src_path = os.path.join(tmpdir, f"track_{i+1:02d}_src")
            with open(src_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)

            wav_path = os.path.join(tmpdir, f"track_{i+1:02d}.wav")
            self._set_status(_("Converting: {name}").format(name=name))
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    src_path,
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-f",
                    "wav",
                    wav_path,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self._set_status(
                    _("Conversion failed: {name}\n{error}").format(
                        name=name, error=result.stderr.strip()[-400:]
                    )
                )
                return
            wav_files.append(wav_path)
            os.unlink(src_path)
            self._set_progress(
                (i + 1) / total / 2,
                _("Converted {i}/{total}").format(i=i + 1, total=total),
            )

        if self.cancelled:
            return

        self._set_status(_("Starting burn – please do not cancel…"))
        self._set_progress(0.5, _("Burning…"))

        device = resolve_sg_device(self.config.get("cd_device", "/dev/sr0"))
        speed = self.config.get("burn_speed", 4)
        burn_tool = get_burn_tool()
        if not burn_tool:
            self._set_status(
                _("No burn program found.\nPlease install: sudo apt install cdrskin")
            )
            return

        if self.config.get("cd_text", True):
            wav_names = [os.path.basename(f) for f in wav_files]
            cue_text = build_cue_sheet(self.playlist, wav_names, track_artist)
            cue_path = os.path.join(tmpdir, "burn.cue")
            with open(cue_path, "w") as f:
                f.write(cue_text)
            cmd = [
                burn_tool,
                f"dev={device}",
                f"speed={speed}",
                "-v",
                "-dao",
                "-pad",
                f"-cuefile={cue_path}",
            ]
        else:
            cmd = [
                burn_tool,
                f"dev={device}",
                f"speed={speed}",
                "-v",
                "-dao",
                "-audio",
                "-pad",
            ] + wav_files

        returncode, output_lines = self._run_burn_process(cmd)
        self._handle_burn_result(returncode, output_lines)

    def _burn_mp3(self, tmpdir):
        cd_root = os.path.join(tmpdir, "cd_root")
        os.makedirs(cd_root, exist_ok=True)
        total = len(self.playlist)
        total_bytes = 0

        for i, track in enumerate(self.playlist):
            if self.cancelled:
                return
            name = track.get("Name", f"track_{i+1}")
            artist = track_artist(track)
            self._set_status(
                _("Downloading: {artist} - {name} ({i}/{total})").format(
                    artist=artist, name=name, i=i + 1, total=total
                )
            )
            self._set_progress(
                i / total / 2, _("Download {i}/{total}").format(i=i + 1, total=total)
            )

            url = self.client.get_download_url(track["Id"])
            resp = self.client.session.get(url, stream=True)
            resp.raise_for_status()

            src_path = os.path.join(tmpdir, f"track_{i+1:02d}_src")
            with open(src_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)

            dst_name = sanitize_name(f"{i+1:02d} - {artist} - {name}") + ".mp3"
            dst_path = os.path.join(cd_root, dst_name)

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "csv=p=0",
                    src_path,
                ],
                capture_output=True,
                text=True,
            )
            codec = probe.stdout.strip().lower()

            if codec == "mp3":
                os.rename(src_path, dst_path)
            else:
                self._set_status(_("Converting: {name}").format(name=name))
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        src_path,
                        "-codec:a",
                        "libmp3lame",
                        "-b:a",
                        f"{MP3_BITRATE_KBPS}k",
                        dst_path,
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    self._set_status(
                        _("Conversion failed: {name}\n{error}").format(
                            name=name, error=result.stderr.strip()[-400:]
                        )
                    )
                    return
                os.unlink(src_path)

            total_bytes += os.path.getsize(dst_path)
            if total_bytes > CD_DATA_MAX_BYTES:
                self._set_status(
                    _("Playlist exceeds data CD capacity (700 MB). Aborting.")
                )
                return

            self._set_progress(
                (i + 1) / total / 2,
                _("Converted {i}/{total}").format(i=i + 1, total=total),
            )

        if self.cancelled:
            return

        self._set_status(_("Creating disc image…"))
        self._set_progress(0.5, _("Building ISO…"))

        iso_tool = get_iso_tool()
        if not iso_tool:
            self._set_status(
                _(
                    "No ISO creation tool found.\nPlease install: sudo apt install xorriso"
                )
            )
            return

        iso_path = os.path.join(tmpdir, "image.iso")
        if iso_tool == "xorriso":
            iso_cmd = [
                "xorriso",
                "-as",
                "mkisofs",
                "-J",
                "-R",
                "-V",
                "JELLYBURN",
                "-o",
                iso_path,
                cd_root,
            ]
        else:
            iso_cmd = [iso_tool, "-J", "-R", "-V", "JELLYBURN", "-o", iso_path, cd_root]

        result = subprocess.run(iso_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self._set_status(
                _("ISO creation failed:\n{error}").format(
                    error=result.stderr.strip()[-400:]
                )
            )
            return

        if self.cancelled:
            return

        self._set_status(_("Starting burn – please do not cancel…"))
        self._set_progress(0.75, _("Burning…"))

        device = resolve_sg_device(self.config.get("cd_device", "/dev/sr0"))
        speed = self.config.get("burn_speed", 4)
        burn_tool = get_burn_tool()
        if not burn_tool:
            self._set_status(
                _("No burn program found.\nPlease install: sudo apt install cdrskin")
            )
            return

        cmd = [burn_tool, f"dev={device}", f"speed={speed}", "-v", "-data", iso_path]
        returncode, output_lines = self._run_burn_process(cmd)
        self._handle_burn_result(returncode, output_lines)
