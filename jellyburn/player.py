import json
import socket
import subprocess
import threading
import time

from .config import seconds_to_mmss

_IPC_PATH = "/tmp/jellyburn-mpv.sock"

EQ_FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def build_eq_filter(bands_db):
    if not bands_db or all(abs(g) < 0.01 for g in bands_db):
        return ""
    entries = ";".join(
        f"entry({freq},{gain})" for freq, gain in zip(EQ_FREQS, bands_db)
    )
    return f"lavfi=[firequalizer=gain_entry='{entries}':gain='cubic_interpolate(f)']"


class Player:
    def __init__(self):
        self._proc = None
        self._seek_target = None  # seconds, set by seek()
        self._paused = False
        self._eq_bands = [0.0] * len(EQ_FREQS)
        self._eq_enabled = False

    @property
    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None

    @property
    def is_paused(self):
        return self._paused

    def play(
        self, url, track, ticks_to_seconds, on_progress, on_error=None, on_finished=None
    ):
        self.stop()
        self._seek_target = None
        self._paused = False
        args = [
            "mpv",
            "--no-video",
            "--really-quiet",
            f"--input-ipc-server={_IPC_PATH}",
        ]
        if self._eq_enabled:
            eq_filter = build_eq_filter(self._eq_bands)
            if eq_filter:
                args.append(f"--af={eq_filter}")
        args.append(url)
        try:
            self._proc = subprocess.Popen(args)
        except FileNotFoundError:
            if on_error:
                on_error("mpv nicht gefunden – bitte mpv installieren")
            return
        threading.Thread(
            target=self._track_loop,
            args=(self._proc, track, ticks_to_seconds, on_progress, on_finished),
            daemon=True,
        ).start()

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self._paused = False

    def pause(self):
        if not self.is_playing or self._paused:
            return
        self._paused = True
        self._send_ipc(["set_property", "pause", True])

    def resume(self):
        if not self.is_playing or not self._paused:
            return
        self._paused = False
        self._send_ipc(["set_property", "pause", False])

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()

    def seek(self, seconds):
        self._seek_target = seconds
        self._send_ipc(["seek", seconds, "absolute"])

    def set_eq(self, bands_db, enabled):
        self._eq_bands = list(bands_db)
        self._eq_enabled = enabled
        if self.is_playing:
            eq_filter = build_eq_filter(self._eq_bands) if enabled else ""
            self._send_ipc(["af", "set", eq_filter])

    def _send_ipc(self, command):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect(_IPC_PATH)
            cmd = json.dumps({"command": command}) + "\n"
            sock.send(cmd.encode())
            sock.close()
        except Exception:
            pass

    def _track_loop(self, proc, track, ticks_to_seconds, on_progress, on_finished=None):
        total = ticks_to_seconds(track.get("RunTimeTicks", 0)) if track else 0
        start = time.monotonic()
        interval = 0.5
        while proc.poll() is None:
            if self._seek_target is not None:
                start = time.monotonic() - self._seek_target
                self._seek_target = None
            if self._paused:
                # Elapsed time is derived from the wall clock, not queried
                # from mpv, so freeze it by pushing 'start' forward by the
                # same amount each sleep advances real time.
                start += interval
            elapsed = time.monotonic() - start
            fraction = min(elapsed / total, 1.0) if total else 0
            time_str = seconds_to_mmss(elapsed) + (
                f" / {seconds_to_mmss(total)}" if total else ""
            )
            on_progress(fraction, time_str, elapsed, total)
            time.sleep(interval)
        if on_finished:
            on_finished()
