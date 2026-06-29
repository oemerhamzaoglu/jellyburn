import subprocess
import threading
import time

from .config import seconds_to_mmss


class Player:
    def __init__(self):
        self._proc = None

    @property
    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None

    def play(self, url, track, ticks_to_seconds, on_progress, on_error=None):
        self.stop()
        try:
            self._proc = subprocess.Popen(
                ["mpv", "--no-video", "--really-quiet", url]
            )
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

    def _track_loop(self, proc, track, ticks_to_seconds, on_progress):
        total = ticks_to_seconds(track.get("RunTimeTicks", 0)) if track else 0
        start = time.monotonic()
        while proc.poll() is None:
            elapsed = time.monotonic() - start
            fraction = min(elapsed / total, 1.0) if total else 0
            time_str = seconds_to_mmss(elapsed) + (f" / {seconds_to_mmss(total)}" if total else "")
            on_progress(fraction, time_str)
            time.sleep(0.5)
