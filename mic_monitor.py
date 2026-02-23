"""
mic_monitor.py
──────────────
Thread-sicherer Mic-Monitor mit Event-basiertem Geräte-Wechsel.
"""

import threading
import time
import numpy as np
import pyaudiowpatch as pyaudio
from audio_devices import AudioDevice
from config import (
    SPEAK_THRESHOLD_RMS, PING_FREQUENCY_HZ,
    PING_DURATION_MS, SILENCE_LEVELS
)

SAMPLE_RATE = 16000
CHUNK_SIZE  = 512


def _generate_ping(freq=PING_FREQUENCY_HZ, duration_ms=PING_DURATION_MS,
                   sample_rate=44100, volume=0.4) -> bytes:
    n_samples = int(sample_rate * duration_ms / 1000)
    t         = np.linspace(0, duration_ms / 1000, n_samples, endpoint=False)
    fade      = int(n_samples * 0.1)
    envelope  = np.ones(n_samples)
    envelope[:fade]  = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    wave_data = (np.sin(2 * np.pi * freq * t) * envelope * volume * 32767).astype(np.int16)
    return wave_data.tobytes()


class MicMonitor:

    def __init__(self):
        self.last_spoke_at = time.time()
        self.current_rms   = 0.0
        self.silence_level = 0
        self._callbacks    = []
        self._ping_played  = {}
        self._running      = False
        self._thread       = None
        self._current_device : AudioDevice | None = None
        self._pending_device : AudioDevice | None = None
        self._device_change  = threading.Event()
        self._enabled        = False

    def start(self, device: AudioDevice | None = None):
        self._pending_device = device
        self._enabled        = device is not None
        self._running        = True
        self._device_change.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._device_change.set()

    def set_device(self, device: AudioDevice | None):
        self._pending_device = device
        self._enabled        = device is not None
        self._device_change.set()
        if device is None:
            self.current_rms   = 0.0
            self.silence_level = 0
            self._ping_played  = {}
            self._notify(0, 0.0)

    def register_callback(self, fn):
        self._callbacks.append(fn)

    def seconds_since_last_speech(self) -> float:
        return time.time() - self.last_spoke_at

    def _run(self):
        pa     = None
        stream = None

        def _close():
            nonlocal pa, stream
            if stream:
                try: stream.stop_stream()
                except Exception: pass
                try: stream.close()
                except Exception: pass
                stream = None
            if pa:
                try: pa.terminate()
                except Exception: pass
                pa = None

        while self._running:
            if self._device_change.is_set():
                self._device_change.clear()
                _close()
                self._current_device = self._pending_device
                if self._enabled and self._current_device is not None:
                    try:
                        pa = pyaudio.PyAudio()
                        stream = pa.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=SAMPLE_RATE,
                            input=True,
                            input_device_index=self._current_device.index,
                            frames_per_buffer=CHUNK_SIZE
                        )
                        print(f"[MicMonitor] Gerät: {self._current_device.name}")
                    except Exception as e:
                        print(f"[MicMonitor] Stream-Fehler: {e}")
                        _close()
                        time.sleep(0.5)
                        continue

            if not self._enabled or stream is None:
                time.sleep(0.05)
                continue

            try:
                data  = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms   = float(np.sqrt(np.mean(audio ** 2)))
                self.current_rms = rms

                if rms >= SPEAK_THRESHOLD_RMS:
                    self.last_spoke_at = time.time()
                    if self.silence_level != 0:
                        self.silence_level = 0
                        self._ping_played  = {}
                        self._notify(0, 0.0)
                else:
                    silence_s = self.seconds_since_last_speech()
                    new_level = sum(1 for t in SILENCE_LEVELS if silence_s >= t)
                    if new_level != self.silence_level:
                        self.silence_level = new_level
                        self._notify(new_level, silence_s)
                        if new_level > 0 and not self._ping_played.get(new_level):
                            self._ping_played[new_level] = True
                            threading.Thread(
                                target=self._play_ping,
                                args=(new_level,), daemon=True
                            ).start()

            except Exception as e:
                print(f"[MicMonitor] Lese-Fehler: {e}")
                _close()
                time.sleep(0.2)
                continue

        _close()

    def _notify(self, level: int, silence_s: float):
        for fn in self._callbacks:
            try: fn(level, silence_s)
            except Exception: pass

    def _play_ping(self, level: int):
        ping_pcm = _generate_ping(
            freq=PING_FREQUENCY_HZ + (level - 1) * 120,
            duration_ms=PING_DURATION_MS
        )
        pa = pyaudio.PyAudio()
        try:
            s = pa.open(format=pyaudio.paInt16, channels=1,
                        rate=44100, output=True)
            for _ in range(level):
                s.write(ping_pcm)
                time.sleep(0.15)
            s.stop_stream()
            s.close()
        except Exception as e:
            print(f"[MicMonitor] Ping-Fehler: {e}")
        finally:
            pa.terminate()


# ── Speaker-Level Monitor ────────────────────────────────────

class SpeakerMonitor:
    """
    Misst den RMS-Pegel des Loopback-Streams.

    Kernproblem bisher:
      - push_chunk() bekam 3s-Blöcke → peak_hold 300ms längst abgelaufen
      - np.mean() über 3s → mittelt Stille mit rein → viel zu niedrig
      - Decay lief bei jedem push_chunk()-Aufruf (alle 3s!) statt bei jedem UI-Tick

    Lösung:
      - push_chunk() zerlegt den Block in 50ms-Fenster → echter Peak
      - tick_decay() wird vom UI-Loop (60ms) aufgerufen → sauberes Abklingen
    """

    def __init__(self):
        self.current_rms    = 0.0
        self._peak_rms      = 0.0
        self._last_push     = 0.0
        self._decay_per_tick = 0.88   # pro 60ms-Tick: nach ~1.2s auf ~0

    def push_chunk(self, audio: np.ndarray, sample_rate: int = 16000):
        """
        audio: float32 normalisiert (0.0–1.0).
        Zerlegt in 50ms-Fenster und nimmt den höchsten RMS-Wert → echter Pegel.
        """
        window_size = max(1, int(sample_rate * 0.05))   # 50ms
        peak = 0.0
        for start in range(0, len(audio), window_size):
            window = audio[start : start + window_size]
            if len(window) == 0:
                continue
            rms = float(np.sqrt(np.mean(window ** 2)))
            if rms > peak:
                peak = rms

        if peak > self._peak_rms:
            self._peak_rms = peak

        self.current_rms = self._peak_rms
        self._last_push  = time.time()

    def tick_decay(self):
        """
        Vom UI-Update-Loop (alle 60ms) aufrufen.
        Lässt den Pegel nach 200ms ohne neuen Chunk abklingen.
        """
        if time.time() - self._last_push > 0.2:
            self._peak_rms  *= self._decay_per_tick
            self.current_rms = self._peak_rms
            if self._peak_rms < 0.0001:
                self._peak_rms   = 0.0
                self.current_rms = 0.0