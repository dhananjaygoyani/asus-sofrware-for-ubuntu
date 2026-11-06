"""Sound level for music-reactive lighting. Only a loudness number is kept; audio isn't stored."""
import array
import math
import shutil
import subprocess
import threading

RATE = 8000
CHUNK = 1024


def level_from_samples(data):
    """Loudness from 0 to 1 for signed 16-bit samples."""
    usable = len(data) - len(data) % 2
    if not usable:
        return 0.0
    samples = array.array("h", data[:usable])
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return min(1.0, rms / 12000)


class MusicMeter:
    """Listens to what the laptop is playing, through PipeWire. Runs only while the music effect is on."""

    def __init__(self):
        self.level = 0.0
        self.process = None

    @staticmethod
    def available():
        return shutil.which("pw-record") is not None

    def start(self):
        if self.process or not self.available():
            return
        self.process = subprocess.Popen(
            ["pw-record", "-P", "{ stream.capture.sink=true }", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def _read(self, process):
        while True:
            data = process.stdout.read(CHUNK)
            if not data:
                break
            # A quick rise and a slower fall reads better on the keyboard.
            new = level_from_samples(data)
            self.level = new if new > self.level else self.level * 0.85 + new * 0.15
        self.level = 0.0

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=2)
            self.process = None
        self.level = 0.0
