import json
import socket
import subprocess
import threading
import time

from .config import seconds_to_mmss

_IPC_PATH = "/tmp/jellyburn-mpv.sock"


class Player:
    def __init__(self):
        self._proc = None
        self._seek_target = None  # seconds, set by seek()

    @property
    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None

    def play(self, url, track, ticks_to_seconds, on_progress, on_error=None):
        self.stop()
        self._seek_target = None
        try:
            self._proc = subprocess.Popen([
                "mpv", "--no-video", "--really-quiet",
                f"--input-ipc-server={_IPC_PATH}",
                url,
            ])
        except FileNotFoundError:
            if on_error:
                on_error("mpv nicht gefunden – bitte mpv installieren")
            return
        threading.Thread(
            target=self._track_loop,
            args=(self._proc, track, ticks_to_seconds, on_progress),
            daemon=True,
        ).start()

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None

    def seek(self, seconds):
        self._seek_target = seconds
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect(_IPC_PATH)
            cmd = json.dumps({"command": ["seek", seconds, "absolute"]}) + "\n"
            sock.send(cmd.encode())
            sock.close()
        except Exception:
            pass

    def _track_loop(self, proc, track, ticks_to_seconds, on_progress):
        total = ticks_to_seconds(track.get("RunTimeTicks", 0)) if track else 0
        start = time.monotonic()
        while proc.poll() is None:
            if self._seek_target is not None:
                start = time.monotonic() - self._seek_target
                self._seek_target = None
            elapsed = time.monotonic() - start
            fraction = min(elapsed / total, 1.0) if total else 0
            time_str = seconds_to_mmss(elapsed) + (f" / {seconds_to_mmss(total)}" if total else "")
            on_progress(fraction, time_str, elapsed, total)
            time.sleep(0.5)
