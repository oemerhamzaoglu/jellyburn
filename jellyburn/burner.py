import os
import resource
import subprocess

from .api import track_artist
from .config import (
    CD_DATA_MAX_BYTES,
    MP3_BITRATE_KBPS,
    get_burn_tool,
    get_iso_tool,
)
from .i18n import _
from .playlists import sanitize_name


class BurnPrereqError(Exception):
    pass


class BurnCallbacks:
    """Bundle of UI-side callbacks the burn pipeline reports through.

    Keeps this module free of any GTK import - the dialog decides how
    on_status/on_progress get marshaled onto the main thread.
    """

    def __init__(self, on_status, on_progress, is_cancelled):
        self.on_status = on_status
        self.on_progress = on_progress
        self.is_cancelled = is_cancelled


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


def download_track(client, track, index, tmpdir):
    url = client.get_download_url(track["Id"])
    resp = client.session.get(url, stream=True)
    resp.raise_for_status()
    src_path = os.path.join(tmpdir, f"track_{index+1:02d}_src")
    with open(src_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return src_path


def probe_codec(path):
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
            path,
        ],
        capture_output=True,
        text=True,
    )
    return probe.stdout.strip().lower()


def convert_to_wav(src, dst):
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "44100", "-ac", "2", "-f", "wav", dst],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()[-400:]
    return True, ""


def convert_to_mp3(src, dst):
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src,
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{MP3_BITRATE_KBPS}k",
            dst,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()[-400:]
    return True, ""


def resolve_burn_prereqs(config):
    device = resolve_sg_device(config.get("cd_device", "/dev/sr0"))
    speed = config.get("burn_speed", 4)
    burn_tool = get_burn_tool()
    if not burn_tool:
        raise BurnPrereqError(
            _("No burn program found.\nPlease install: sudo apt install cdrskin")
        )
    return device, speed, burn_tool


def build_iso(cd_root, iso_path):
    iso_tool = get_iso_tool()
    if not iso_tool:
        return False, _(
            "No ISO creation tool found.\nPlease install: sudo apt install xorriso"
        )
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
        return False, _("ISO creation failed:\n{error}").format(
            error=result.stderr.strip()[-400:]
        )
    return True, ""


def _raise_memlock():
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


def run_burn_process(cmd, on_output_line):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=_raise_memlock,
    )
    output_lines = []
    for line in proc.stdout:
        line = line.strip()
        output_lines.append(line)
        if "%" in line or "Track" in line or "Writing" in line:
            on_output_line(line)
    proc.wait()
    return proc.returncode, output_lines


def interpret_burn_result(returncode, output_lines):
    if returncode == 0:
        return True, _("CD burned successfully!")
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
        return False, hint
    return False, _("Burn error (code {code}):\n{output}").format(
        code=returncode, output=full
    )


def run_audio_burn(playlist, client, config, tmpdir, cb):
    wav_files = []
    total = len(playlist)
    for i, track in enumerate(playlist):
        if cb.is_cancelled():
            return
        name = track.get("Name", f"track_{i+1}")
        artist = track_artist(track)
        cb.on_status(
            _("Downloading: {artist} - {name} ({i}/{total})").format(
                artist=artist, name=name, i=i + 1, total=total
            )
        )
        cb.on_progress(
            i / total / 2, _("Download {i}/{total}").format(i=i + 1, total=total)
        )

        src_path = download_track(client, track, i, tmpdir)

        wav_path = os.path.join(tmpdir, f"track_{i+1:02d}.wav")
        cb.on_status(_("Converting: {name}").format(name=name))
        ok, err = convert_to_wav(src_path, wav_path)
        if not ok:
            cb.on_status(
                _("Conversion failed: {name}\n{error}").format(name=name, error=err)
            )
            return
        wav_files.append(wav_path)
        os.unlink(src_path)
        cb.on_progress(
            (i + 1) / total / 2,
            _("Converted {i}/{total}").format(i=i + 1, total=total),
        )

    if cb.is_cancelled():
        return

    cb.on_status(_("Starting burn – please do not cancel…"))
    cb.on_progress(0.5, _("Burning…"))

    try:
        device, speed, burn_tool = resolve_burn_prereqs(config)
    except BurnPrereqError as e:
        cb.on_status(str(e))
        return

    if config.get("cd_text", True):
        wav_names = [os.path.basename(f) for f in wav_files]
        cue_text = build_cue_sheet(playlist, wav_names, track_artist)
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

    returncode, output_lines = run_burn_process(cmd, cb.on_status)
    success, message = interpret_burn_result(returncode, output_lines)
    cb.on_status(message)
    if success:
        cb.on_progress(1.0, _("Done!"))


def run_mp3_burn(playlist, client, config, tmpdir, cb):
    cd_root = os.path.join(tmpdir, "cd_root")
    os.makedirs(cd_root, exist_ok=True)
    total = len(playlist)
    total_bytes = 0

    for i, track in enumerate(playlist):
        if cb.is_cancelled():
            return
        name = track.get("Name", f"track_{i+1}")
        artist = track_artist(track)
        cb.on_status(
            _("Downloading: {artist} - {name} ({i}/{total})").format(
                artist=artist, name=name, i=i + 1, total=total
            )
        )
        cb.on_progress(
            i / total / 2, _("Download {i}/{total}").format(i=i + 1, total=total)
        )

        src_path = download_track(client, track, i, tmpdir)

        dst_name = sanitize_name(f"{i+1:02d} - {artist} - {name}") + ".mp3"
        dst_path = os.path.join(cd_root, dst_name)

        codec = probe_codec(src_path)
        if codec == "mp3":
            os.rename(src_path, dst_path)
        else:
            cb.on_status(_("Converting: {name}").format(name=name))
            ok, err = convert_to_mp3(src_path, dst_path)
            if not ok:
                cb.on_status(
                    _("Conversion failed: {name}\n{error}").format(name=name, error=err)
                )
                return
            os.unlink(src_path)

        total_bytes += os.path.getsize(dst_path)
        if total_bytes > CD_DATA_MAX_BYTES:
            cb.on_status(_("Playlist exceeds data CD capacity (700 MB). Aborting."))
            return

        cb.on_progress(
            (i + 1) / total / 2,
            _("Converted {i}/{total}").format(i=i + 1, total=total),
        )

    if cb.is_cancelled():
        return

    cb.on_status(_("Creating disc image…"))
    cb.on_progress(0.5, _("Building ISO…"))

    iso_path = os.path.join(tmpdir, "image.iso")
    ok, msg = build_iso(cd_root, iso_path)
    if not ok:
        cb.on_status(msg)
        return

    if cb.is_cancelled():
        return

    cb.on_status(_("Starting burn – please do not cancel…"))
    cb.on_progress(0.75, _("Burning…"))

    try:
        device, speed, burn_tool = resolve_burn_prereqs(config)
    except BurnPrereqError as e:
        cb.on_status(str(e))
        return

    cmd = [burn_tool, f"dev={device}", f"speed={speed}", "-v", "-data", iso_path]
    returncode, output_lines = run_burn_process(cmd, cb.on_status)
    success, message = interpret_burn_result(returncode, output_lines)
    cb.on_status(message)
    if success:
        cb.on_progress(1.0, _("Done!"))
