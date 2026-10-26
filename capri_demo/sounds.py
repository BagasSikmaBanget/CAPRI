"""Capri's cue set, synthesized from capri-desktop's voice.js.

Every cue is rendered to a small 16-bit mono WAV in the temp folder and played
with winsound, so no audio files ship. The palette mirrors voice.js:
teleport-out/in, done, alert, error, hello, blip, tick, star, land, rise,
bolt, charge and possess.
"""

from __future__ import annotations

import io
import math
import os
import random
import tempfile
import threading
import time
import wave
from array import array

try:
    import winsound
except Exception:  # noqa: BLE001
    winsound = None

SR = 22050
TAU = math.tau
BLIP_NOTES = [62, 65, 67, 69, 72, 74, 77, 79]

# Old beep patterns are only a fallback when WAV generation fails.
BEEPS = {
    "hello": [(660, 90), (880, 90), (1046, 140)],
    "alert": [(880, 90), (660, 90), (880, 90), (660, 160)],
    "error": [(220, 140), (165, 220)],
    "done": [(523, 90), (659, 90), (784, 90), (1046, 180)],
    "teleport": [(1200, 50), (900, 50)],
    "land": [(300, 60), (180, 100)],
    "tick": [(1000, 40)],
    "star": [(784, 120), (1046, 160), (1318, 220)],
}


def _midi(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def _buf(seconds: float) -> list[float]:
    return [0.0] * max(1, int(SR * max(0.02, seconds)))


def _env(t: float, dur: float, attack: float = 0.004) -> float:
    if t < attack:
        return t / attack if attack > 0 else 1.0
    return math.exp(-5.0 * (t - attack) / max(0.02, dur))


def _osc(
    buf: list[float],
    kind: str,
    freq: float,
    start: float,
    dur: float,
    peak: float,
    end_freq: float | None = None,
) -> None:
    n0 = int(start * SR)
    n = max(1, int(dur * SR))
    phase = 0.0
    for i in range(n):
        t = i / SR
        f = freq if end_freq is None else freq * ((end_freq / freq) ** (t / dur))
        phase += TAU * f / SR
        if kind == "sine":
            v = math.sin(phase)
        elif kind == "square":
            v = 1.0 if math.sin(phase) >= 0.0 else -1.0
        elif kind == "triangle":
            v = (2.0 / math.pi) * math.asin(math.sin(phase))
        else:  # sawtooth
            v = 2.0 * ((phase / TAU) % 1.0) - 1.0
        idx = n0 + i
        if 0 <= idx < len(buf):
            buf[idx] += v * peak * _env(t, dur)


def _noise(
    buf: list[float],
    start: float,
    dur: float,
    peak: float,
    frm: float,
    to: float,
    q: float = 2.0,
) -> None:
    """A swept band-pass noise burst (stable biquad band-pass)."""
    n0 = int(start * SR)
    n = max(1, int(dur * SR))
    x1 = x2 = y1 = y2 = 0.0
    for i in range(n):
        t = i / SR
        fc = frm * ((to / frm) ** (t / dur)) if frm > 0 and to > 0 else frm
        fc = max(60.0, min(fc, SR * 0.45))
        w0 = TAU * fc / SR
        alpha = math.sin(w0) / (2.0 * max(0.2, q))
        a0 = 1.0 + alpha
        b0 = alpha
        b2 = -alpha
        a1 = -2.0 * math.cos(w0)
        a2 = 1.0 - alpha
        x0 = random.uniform(-1.0, 1.0)
        y0 = (b0 * x0 + b2 * x2 - a1 * y1 - a2 * y2) / a0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
        idx = n0 + i
        if 0 <= idx < len(buf):
            buf[idx] += y0 * peak * _env(t, dur)


def _zap(buf: list[float], arriving: bool, offset: float = 0.0) -> None:
    if arriving:
        _osc(buf, "sawtooth", 1600, offset, 0.22, 0.12, 140)
        _noise(buf, offset, 0.2, 0.22, 6000, 500, 3)
    else:
        _osc(buf, "sawtooth", 180, offset, 0.22, 0.12, 2400)
        _noise(buf, offset, 0.2, 0.22, 400, 7000, 3)
    for i in range(4):
        _osc(
            buf,
            "square",
            random.uniform(800, 3200),
            offset + 0.02 + i * 0.035,
            0.02,
            0.05,
        )
    if arriving:
        _osc(buf, "triangle", 70, offset + 0.16, 0.18, 0.3)


def _done() -> list[float]:
    b = _buf(0.9)
    for i, note in enumerate((64, 68, 71, 75, 76)):
        _osc(b, "triangle", _midi(note + 12), i * 0.07, 0.28, 0.09)
        _osc(b, "square", _midi(note), i * 0.07, 0.12, 0.035)
    for i in range(7):
        _osc(b, "square", random.uniform(1200, 4200), 0.4 + i * 0.03, 0.018, 0.035)
    return b


def _alert() -> list[float]:
    b = _buf(0.7)
    for r in range(2):
        _osc(b, "square", 988, r * 0.28, 0.09, 0.07)
        _osc(b, "square", 740, r * 0.28 + 0.11, 0.11, 0.07)
    return b


def _error() -> list[float]:
    b = _buf(0.5)
    _osc(b, "sawtooth", 110, 0.0, 0.32, 0.14, 55)
    _noise(b, 0.0, 0.25, 0.15, 900, 200, 1.2)
    return b


def _hello() -> list[float]:
    b = _buf(0.45)
    for i, note in enumerate((69, 76, 81)):
        _osc(b, "square", _midi(note), i * 0.06, 0.07, 0.06)
    _noise(b, 0.18, 0.08, 0.06, 2000, 8000, 5)
    return b


def _blip(mood: str = "talk") -> list[float]:
    b = _buf(0.12)
    offset = 5 if mood == "alert" else -7 if mood == "error" else 0
    note = random.choice(BLIP_NOTES) + offset
    f = _midi(note)
    _osc(b, "square", f, 0.0, 0.035, 0.035)
    _osc(b, "triangle", f * 1.498, 0.004, 0.03, 0.025)
    _osc(b, "square", f * 0.501, 0.008, 0.03, 0.018)
    return b


def _tick() -> list[float]:
    b = _buf(0.06)
    _noise(b, 0.0, 0.03, 0.12, 3000, 9000, 8)
    return b


def _star() -> list[float]:
    b = _buf(1.35)
    _osc(b, "sine", _midi(93), 0.0, 0.9, 0.05)
    _osc(b, "sine", _midi(100), 0.14, 1.2, 0.035)
    _noise(b, 0.05, 0.6, 0.015, 9000, 12000, 6)
    return b


def _land() -> list[float]:
    b = _buf(0.3)
    _osc(b, "triangle", 150, 0.0, 0.14, 0.22, 48)
    _noise(b, 0.0, 0.06, 0.08, 1800, 400, 1.5)
    return b


def _rise() -> list[float]:
    b = _buf(0.35)
    _osc(b, "sawtooth", 160, 0.0, 0.2, 0.07, 1400)
    _noise(b, 0.0, 0.18, 0.12, 500, 6000, 2)
    return b


def _bolt(soft: bool = False) -> list[float]:
    b = _buf(0.5)
    k = 0.35 if soft else 1.0
    _osc(b, "sawtooth", 62, 0.0, 0.3 * k + 0.05, 0.08 * k)
    for i in range(3 if soft else 8):
        _noise(
            b,
            i * random.uniform(0.02, 0.045),
            0.025,
            0.14 * k,
            random.uniform(2500, 6000),
            random.uniform(4000, 9000),
            6,
        )
    return b


def _charge() -> list[float]:
    b = _buf(0.8)
    _osc(b, "sawtooth", 55, 0.0, 0.6, 0.07, 240)
    for i in range(6):
        _noise(b, 0.08 + i * 0.09, 0.02, 0.04 + i * 0.016, 3000, 7000, 6)
    return b


def _possess() -> list[float]:
    b = _buf(0.6)
    for i, note in enumerate((79, 76, 72)):
        at = i * 0.11
        _osc(b, "square", _midi(note), at, 0.07, 0.05)
        _osc(b, "square", _midi(note) * 1.012, at + 0.004, 0.06, 0.035)
        _osc(b, "triangle", _midi(note - 12), at + 0.008, 0.07, 0.04)
    _noise(b, 0.0, 0.3, 0.05, 1200, 5000, 3)
    return b


def _teleport() -> list[float]:
    out = _buf(0.45)
    _zap(out, False)
    inn = _buf(0.45)
    _zap(inn, True)
    return out + [0.0] * int(SR * 0.12) + inn


def _wav(samples: list[float]) -> bytes:
    vals = [math.tanh(v * 3.2 * 1.6) / math.tanh(1.6) for v in samples]
    peak = max((abs(v) for v in vals), default=0.0)
    scale = 0.85 / peak if peak > 0.85 else 1.0
    pcm = array("h", (int(max(-1.0, min(1.0, v * scale)) * 32767) for v in vals))
    with io.BytesIO() as raw:
        with wave.open(raw, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SR)
            out.writeframes(pcm.tobytes())
        return raw.getvalue()


def _build(name: str) -> bytes:
    if name == "teleport-out":
        b = _buf(0.45)
        _zap(b, False)
        return _wav(b)
    if name == "teleport-in":
        b = _buf(0.45)
        _zap(b, True)
        return _wav(b)
    if name == "teleport":
        return _wav(_teleport())
    if name == "done":
        return _wav(_done())
    if name == "alert":
        return _wav(_alert())
    if name == "error":
        return _wav(_error())
    if name == "hello":
        return _wav(_hello())
    if name == "blip":
        return _wav(_blip())
    if name == "blip-alert":
        return _wav(_blip("alert"))
    if name == "blip-error":
        return _wav(_blip("error"))
    if name == "tick":
        return _wav(_tick())
    if name == "star":
        return _wav(_star())
    if name == "land":
        return _wav(_land())
    if name == "rise":
        return _wav(_rise())
    if name == "bolt":
        return _wav(_bolt(False))
    if name == "bolt-soft":
        return _wav(_bolt(True))
    if name == "charge":
        return _wav(_charge())
    if name == "possess":
        return _wav(_possess())
    return b""


CUES = (
    "teleport-out",
    "teleport-in",
    "teleport",
    "done",
    "alert",
    "error",
    "hello",
    "blip",
    "blip-alert",
    "blip-error",
    "tick",
    "star",
    "land",
    "rise",
    "bolt",
    "bolt-soft",
    "charge",
    "possess",
)


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._paths: dict[str, str] = {}
        self._building: set[str] = set()
        self._wanted: set[str] = set()
        self._dir = os.path.join(tempfile.gettempdir(), "capri-demo-sounds")
        if enabled and winsound is not None:
            threading.Thread(target=self._prewarm, name="capri-sounds", daemon=True).start()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled and winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:  # noqa: BLE001
                pass

    def play(self, name: str) -> None:
        if not self.enabled or winsound is None:
            return
        path = self._paths.get(name)
        if path is not None:
            self._play(path)
            return
        with self._lock:
            self._wanted.add(name)
            if name in self._building:
                return
            self._building.add(name)
        threading.Thread(
            target=self._build_one, args=(name,), name=f"capri-sound-{name}", daemon=True
        ).start()

    def _play(self, path: str) -> None:
        try:
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception:  # noqa: BLE001
            pass

    def _prewarm(self) -> None:
        for name in CUES:
            self._ensure(name)

    def _ensure(self, name: str) -> None:
        if name in self._paths:
            return
        try:
            data = _build(name)
            if not data:
                return
            os.makedirs(self._dir, exist_ok=True)
            path = os.path.join(self._dir, f"{name}.wav")
            with open(path, "wb") as fh:
                fh.write(data)
            with self._lock:
                self._paths[name] = path
        except Exception:  # noqa: BLE001
            self._beep(name)

    def _build_one(self, name: str) -> None:
        try:
            self._ensure(name)
            with self._lock:
                wanted = name in self._wanted
                self._wanted.discard(name)
                self._building.discard(name)
                path = self._paths.get(name)
            if wanted and path is not None and self.enabled:
                self._play(path)
        except Exception:  # noqa: BLE001
            with self._lock:
                self._building.discard(name)

    def _beep(self, name: str) -> None:
        pattern = BEEPS.get(name)
        if not pattern or winsound is None:
            return
        try:
            for freq, ms in pattern:
                winsound.Beep(int(freq), int(ms))
                time.sleep(0.01)
        except Exception:  # noqa: BLE001
            pass
